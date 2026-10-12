"""Carries out the action chosen by router.route(): database updates, calendar calls and Telegram messages.
Each function mirrors one branch of the original n8n workflow."""
from __future__ import annotations

import logging
import re

from .calendar_service import CalendarError
from .clinic import Clinic
from .db import DB
from .i18n import ASK_TEXT, LANG_BUTTONS, I18n
from .reports import build_staff_report
from .router import route
from .slots import compute_available_dates, compute_free_slots
from .texts import (CALENDAR_DOWN, DATE_WAITLIST_HINT, TIME_WAITLIST_HINT, HOME_KB, INFO_HINT, L, NAV, RETRY_KB, S, STAFF_KB, TRY_OTHER, WAITLIST_HINT, WELCOME,
                    WELCOME_KB)
from .timeutil import HOUR, MIN, local_stamp, now_ms, parse_ms, start_of_day_iso, start_of_month_plus

log = logging.getLogger(__name__)


def rows_of(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def btn(text, **kw):
    return {"text": text, **kw}


class Bot:
    """Glue between the router output and the outside world.
    `messenger` sends Telegram messages (see main.TelegramMessenger), `calendar` is Google Calendar or MemoryCalendar."""

    def __init__(self, db: DB, clinic: Clinic, calendar, messenger, i18n: I18n | None = None):
        self.db, self.clinic, self.cal, self.tg = db, clinic, calendar, messenger
        self.i18n = i18n or I18n(None, ["hy"])

    # ------------------------------------------------------------------ one Telegram update
    async def handle_update(self, p: dict) -> None:
        """Language step (only when several languages are configured), then router + action."""
        if not self.i18n.enabled and self.i18n.vocab:
            p = self.i18n.incoming(p, {})
        if self.i18n.enabled:
            saved = self.db.get_lang(p["chat_id"]) if p.get("chat_id") and self.db.has_lang(p["chat_id"]) else ""
            p = self.i18n.incoming(p, {p["chat_id"]: saved} if saved else {})
            if p["ask_lang"]:
                await self.tg.send(p["chat_id"], ASK_TEXT, reply_kb=LANG_BUTTONS)
                return
            if p["set_lang"]:
                self.db.set_lang(p["chat_id"], p["set_lang"])
        session = self.db.get_session(p["chat_id"]) if p.get("chat_id") else {}
        req = self.db.get_request(p["lookup_request_id"]) if p.get("lookup_request_id", "__none__") != "__none__" else None
        out = route(p, session, self.clinic, req, now_ms())
        await self.run(out, p)

    # ------------------------------------------------------------------ helpers
    @property
    def links(self):
        return self.clinic.info.get("links", {})

    def lang_of(self, chat_id) -> str:
        return self.db.get_lang(chat_id) if self.i18n.enabled and chat_id else "hy"

    # Every message is translated into the receiver's language just before sending (n8n: the expression in each Telegram node).
    async def send(self, chat_id, text, kb=None, inline=None, remove_kb=False):
        lg = self.lang_of(chat_id)
        return await self.tg.send(chat_id, self.i18n.translate(text, lg), reply_kb=self.i18n.translate_keyboard(kb, lg),
                                  inline_kb=self.i18n.translate_keyboard(inline, lg), remove_kb=remove_kb)

    async def edit(self, r, p, text, inline=None):
        lg = self.lang_of(r["chat_id"])
        return await self.tg.edit(r["chat_id"], p.get("message_id"), self.i18n.translate(text, lg),
                                  inline_kb=self.i18n.translate_keyboard(inline or [], lg))

    async def answer(self, r, text=None):
        t = r["callback_text"] if text is None else text
        await self.tg.answer(r["callback_id"], self.i18n.translate(t, self.lang_of(r["chat_id"])) if t else t)

    def doctor_list_kb(self, docs):
        return [[d["doctor_name"], d["info_label"]] for d in docs] + [NAV]

    # ------------------------------------------------------------------ dispatcher
    async def run(self, r: dict, p: dict) -> None:
        a = r["action"]
        handler = getattr(self, "a_" + a, None)
        if handler is None:
            log.warning("no handler for action %s", a)
            return
        await handler(r, p)

    # ------------------------------------------------------------------ menus
    async def a_welcome(self, r, p):
        self.db.upsert_session(r["chat_id"], appointment_date="", doctor_key="", doctor_name="", patient_name=r["first_name"],
                               request_id="", selected_time="", service="", slot_options="", stage="idle",
                               updated_note="restarted with /start", replace_request_id="")
        self.db.update_request(r["old_request_id"], "pending", status="cancelled", decided_by="patient_restart")
        await self.send(r["chat_id"], WELCOME.format(place=self.clinic.phrases["welcome_place"]), kb=WELCOME_KB)

    async def _menu(self, r, p):
        self.db.upsert_session(r["chat_id"], service=r["service"], stage=r["menu_stage"], updated_note="menu shown")
        docs = self.clinic.active_doctors()
        a = r["action"]
        if a == "doctor_menu":
            await self.send(r["chat_id"], "Խնդրում ենք ընտրել բժշկին։\n" + INFO_HINT, kb=self.doctor_list_kb(docs))
        elif a == "service_menu":
            kb = [[self.clinic.service_name(sp)] for sp in self.clinic.service_menu] + [NAV]
            if self.clinic.service_name("general"):
                await self.send(r["chat_id"], "Խնդրում ենք ընտրել ծառայության տեսակը։\nԵթե վստահ չեք, ընտրեք «"
                                + self.clinic.service_name("general") + "»՝ բժիշկը կզննի և կառաջարկի հետագա քայլերը։", kb=kb)
            else:
                await self.send(r["chat_id"], "Խնդրում ենք ընտրել ծառայության տեսակը։", kb=kb)
        else:
            spec = {"service_general": "general", "service_pediatric": "pediatric", "service_ortho": "orthodontics"}.get(a) \
                or next((k for k, v in self.clinic.specialties.items() if v.get("name") == r["service"]), "")
            ds = [d for d in docs if d["specialty"] == spec]
            await self.send(r["chat_id"], "Ընտրեք բժշկին՝ " + self.clinic.service_name(spec) + " այցի համար։\n" + INFO_HINT,
                            kb=self.doctor_list_kb(ds))

    a_doctor_menu = a_service_menu = a_service_general = a_service_pediatric = a_service_ortho = a_service_pick = _menu

    async def a_ask_reason(self, r, p):
        self.db.upsert_session(r["chat_id"], appointment_date="", doctor_key=r["doctor_key"], doctor_name=r["doctor_name"],
                               quick_rebook="", replace_request_id="", request_id="", slot_options="", stage="awaiting_reason",
                               updated_note="asking visit reason", visit_reason="")
        labels = r["reason_labels"]
        kb = rows_of(labels, 2) if len(labels) == 4 else [[x] for x in labels]
        await self.send(r["chat_id"], r["reason_text"], kb=kb + [NAV])

    async def a_reply(self, r, p):
        await self.send(r["chat_id"], r["text"], kb=HOME_KB if r["home_kb"] else None)

    async def a_end_chat(self, r, p):
        await self.send(r["chat_id"], "Շնորհակալություն, որ դիմեցիք " + self.clinic.phrases["thanks_to"]
                        + " 🦷\nԵրբ ցանկանաք նոր այց ամրագրել, սեղմեք «🏠 Գլխավոր մենյու»։", kb=[[L["home"], L["myBookings"]]])

    async def a_confirm_cancel(self, r, p):
        await self.send(r["chat_id"], "Ձեր հայտը դեռ սպասում է բժշկի պատասխանին։\nԵթե սկսեք նոր ամրագրում, այս հայտը կչեղարկվի։ Չեղարկե՞լ այն։",
                        kb=[[L["yesCancel"]], [L["noWait"]]])

    async def a_contact(self, r, p):
        c, lk = self.clinic.info, self.links
        text = ("📞 " + self.clinic.phrases["contact_title"] + "\n\n☎️ Հեռախոս՝ " + c["phone"] + "\n📱 Բջջային, WhatsApp, Viber, Telegram՝ " + c["mobile"]
                + "\n\n🕘 Աշխատանքային ժամեր՝ " + c["hours_text"] + "\n📍 " + c["address_short"]
                + "\n\nԶանգահարելու համար սեղմեք համարի վրա։ Գրելու կամ Telegram-ով զանգելու համար ընտրեք ստորև։")
        inline = [[btn("💬 Telegram՝ գրել / զանգել", url=lk["telegram"])],
                  [btn("🟢 WhatsApp", url=lk["whatsapp"]), btn("🟣 Viber", url=lk["viber"])],
                  [btn("📸 Instagram", url=lk["instagram"])],
                  [btn("🗺 Քարտեզ և երթուղի", url=lk["route"])]]
        await self.send(r["chat_id"], text, inline=[row for row in inline if all(b.get("url") for b in row)])

    # ------------------------------------------------------------------ dates and times
    async def a_doctor_chosen(self, r, p):
        self.db.upsert_session(r["chat_id"], appointment_date="", doctor_key=r["doctor_key"], doctor_name=r["doctor_name"],
                               quick_rebook=r["quick_rebook"], request_id="", slot_options="",
                               stage="awaiting_month" if r["month_offset"] == -1 else "awaiting_date",
                               updated_note="doctor chosen", visit_reason=r["visit_reason"])
        await self.show_dates(r)

    async def show_dates(self, r):
        now = now_ms()
        try:
            events = await self.cal.list_events(r["calendar_id"], start_of_day_iso(now), start_of_month_plus(now, 2))
        except CalendarError:
            await self.send(r["chat_id"], CALENDAR_DOWN, remove_kb=True)
            return
        res = compute_available_dates(r, events, self.db.requests_for_doctor(r["doctor_key"]), self.clinic, now)
        if res["pick_month"]:
            await self.send(r["chat_id"], res["reply"], kb=[[x] for x in res["month_labels"]] + [NAV])
        elif res["has_dates"]:
            await self.send(r["chat_id"], res["reply"] + DATE_WAITLIST_HINT, kb=rows_of(res["labels"], 4) + [[res["toggle"], L["waitlist"]], NAV])
        else:
            await self.send(r["chat_id"], res["reply"] + WAITLIST_HINT, kb=[[res["toggle"]], [L["waitlist"]], NAV])

    async def a_check_availability(self, r, p):
        try:
            events = await self.cal.list_events(r["calendar_id"], r["date"] + "T00:00:00+04:00", r["date_next"] + "T00:00:00+04:00")
        except CalendarError:
            if r["mode"] == "approve":
                self.db.update_request(r["request_id"], "approving", status="pending", decided_by="")
            await self.send(r["chat_id"], CALENDAR_DOWN, remove_kb=True)
            return
        holds = self.db.requests_for_doctor(r["doctor_key"], r["date"])
        res = compute_free_slots(r, events, holds, self.clinic, now_ms())
        if r["mode"] == "approve":
            return await self._approve_checked(r, p, res)
        if r["mode"] == "time" and res["ok"]:
            return await self._create_request(r)
        # Date chosen (or the chosen time was just taken): offer the free times.
        self.db.upsert_session(r["chat_id"], appointment_date=r["date"], doctor_key=r["doctor_key"], doctor_name=r["doctor_name"],
                               quick_rebook=r["quick_rebook"], request_id="", slot_options=res["free_json"],
                               stage=res["next_stage"], updated_note="slots offered")
        if res["has_free"]:
            await self.send(r["chat_id"], res["reply"] + TIME_WAITLIST_HINT, kb=rows_of(res["free"], 4) + [[L["waitlist"]], NAV])
        else:
            await self.send(r["chat_id"], res["reply"].replace("«Այլ ամսաթիվ»", "«⬅️ Հետ»՝ այլ օր ընտրելու համար") + WAITLIST_HINT,
                            kb=[[L["waitlist"]], NAV])

    async def _create_request(self, r):
        self.db.insert_request({
            "request_id": r["request_id"], "chat_id": str(r["chat_id"]), "patient_name": r["full_name"], "patient_full_name": r["full_name"],
            "patient_phone": r["phone"], "telegram_username": r["username"], "doctor_key": r["doctor_key"], "service": r["service"],
            "slot_start": r["slot_start"], "slot_end": r["slot_end"], "slot_key": r["slot_key"], "status": "pending",
            "expires_at": r["expires_at"], "replaces_request_id": r["replaces_request_id"]})
        # Two patients could pick overlapping times at the same moment: the request saved first keeps the time.
        now, s0, e0 = now_ms(), parse_ms(r["slot_start"]), parse_ms(r["slot_end"])
        active = []
        for x in self.db.requests_for_doctor(r["doctor_key"], r["date"]):
            st = x["status"]
            if st in ("approving", "approved") or (st == "pending" and (parse_ms(x["expires_at"]) or 0) > now):
                a = parse_ms(x["slot_start"]); b = parse_ms(x["slot_end"]) or a + 30 * MIN
                if a < e0 and b > s0:
                    active.append(x)
        active.sort(key=lambda x: x["id"])
        if not active or active[0]["request_id"] != r["request_id"]:
            self.db.update_request(r["request_id"], "pending", status="conflict", decided_by="slot_taken")
            await self.send(r["chat_id"], "Ցավոք, այս ժամը (" + r["date"] + " " + r["selected_time"] + ") հենց նոր ամրագրվեց այլ պացիենտի կողմից։" + TRY_OTHER, kb=RETRY_KB)
            return
        self.db.upsert_session(r["chat_id"], full_name=r["full_name"], phone=r["phone"], request_id=r["request_id"], slot_options="",
                               stage="awaiting_approval", updated_note="request sent to doctor")
        sent = await self.send(r["approver_chat_id"], r["doctor_message"],
                               inline=[[btn("✅ Հաստատել", callback_data="ap|" + r["request_id"]), btn("❌ Մերժել", callback_data="rj|" + r["request_id"])]])
        if not sent:
            self.db.update_request(r["request_id"], "pending", status="failed", decided_by="doctor_unreachable")
            await self.send(r["chat_id"], "Ներողություն, չհաջողվեց հայտը փոխանցել բժշկին, և այցը չի ամրագրվել։\nՓորձեք կրկին՝ սեղմելով «🏠 Գլխավոր մենյու»։",
                            kb=[[L["home"], L["end"]]])
            return
        await self.send(r["chat_id"], "Ձեր հայտն ուղարկվեց բժշկին՝ " + r["doctor_name"] + "։\nԱյցելու՝ " + r["full_name"] + "\nՀեռախոս՝ " + r["phone"]
                        + "\nԾառայություն՝ " + r["service"] + "\nԱմսաթիվ՝ " + r["date"] + ", ժամ՝ " + r["selected_time"]
                        + "\nՍա դեռ հաստատված այց չէ։ Բժշկի պատասխանը կստանաք այստեղ։", kb=[[L["home"], L["end"]]])

    async def a_ask_name(self, r, p):
        self.db.upsert_session(r["chat_id"], selected_time=r["selected_time"], stage="awaiting_name", updated_note="time chosen, asking name")
        head = "Ընտրված ժամ՝ " + r["date"] + " " + r["selected_time"] + "։\nԽնդրում ենք գրել այցելուի անունը և ազգանունը (օրինակ՝ Անի Պետրոսյան)։"
        if r["saved_name"]:
            await self.send(r["chat_id"], head + "\nԿամ սեղմեք կոճակը՝ նախորդ անունն օգտագործելու համար։", kb=[[r["saved_name"]], NAV])
        else:
            await self.send(r["chat_id"], head, kb=[NAV])

    async def a_ask_phone(self, r, p):
        self.db.upsert_session(r["chat_id"], full_name=r["full_name"], stage="awaiting_phone", updated_note="name entered, asking phone")
        share = [btn(L["sharePhone"], request_contact=True)]
        head = "Շնորհակալություն, " + r["full_name"] + "։\nԽնդրում ենք նշել կապի հեռախոսահամարը, որպեսզի կլինիկան կարողանա կապվել Ձեզ հետ։\n"
        if r["saved_phone"]:
            await self.send(r["chat_id"], head + "Սեղմեք նախորդ համարով կոճակը, «📱 Կիսվել իմ համարով» կոճակը կամ գրեք համարը, օրինակ՝ +374 91 123456։",
                            kb=[[r["saved_phone"]], share, NAV])
        else:
            await self.send(r["chat_id"], head + "Սեղմեք «📱 Կիսվել իմ համարով» կամ գրեք համարը, օրինակ՝ +374 91 123456։", kb=[share, NAV])

    # ------------------------------------------------------------------ doctor approval
    async def a_approve(self, r, p):
        await self.answer(r)
        if not self.db.update_request(r["request_id"], "pending", status="approving", decided_by=r["from_id"]):
            await self.edit(r, p, (p.get("message_text") or "") + "\n\nℹ️ Այս հայտն արդեն մշակված է։")
            return
        await self.a_check_availability(r, p)

    async def _approve_checked(self, r, p, res):
        msg = p.get("message_text") or ""
        if not res["ok"]:
            self.db.update_request(r["request_id"], "approving", status="conflict", decided_by="slot_taken_on_recheck")
            self.db.update_session_if(r["patient_chat_id"], r["request_id"], request_id="", slot_options="", stage="idle", updated_note="slot taken before approval")
            await self.send(r["patient_chat_id"], "Ցավոք, Ձեր ընտրած ժամը (" + r["date"] + " " + r["selected_time"] + ") այլևս ազատ չէ, և այցը չի ստեղծվել։" + TRY_OTHER, kb=RETRY_KB)
            await self.edit(r, p, msg + "\n\n⚠️ Ժամն այլևս ազատ չէ, այցը չի ստեղծվել։ Պացիենտը տեղեկացվել է։")
            return
        prefix = self.clinic.booking.get("event_title_prefix") or ""
        desc = ("Ստեղծվել է " + self.clinic.phrases["created_by"] + " կողմից բժշկի հաստատումից հետո։\nՀայտ՝ " + r["request_id"] + "\nՊացիենտ՝ " + r["patient_name"]
                + "\nՀեռախոս՝ " + (r["phone"] or "—") + "\nTelegram՝ " + ("@" + r["username"] if r["username"] else "—")
                + "\nԾառայություն՝ " + r["service"] + "\nԲժիշկ՝ " + r["doctor_name"])
        try:
            event_id = await self.cal.create_event(r["calendar_id"], r["slot_start"], r["slot_end"],
                                                   prefix + r["doctor_name"] + " — " + r["service"] + " — " + r["patient_name"], desc)
        except CalendarError:
            self.db.update_request(r["request_id"], "approving", status="pending", decided_by="")
            await self.send(r["chat_id"], "⚠️ Օրացույցում այցը չհաջողվեց ստեղծել։ Հայտը մնում է սպասման մեջ․ փորձեք կրկին սեղմել «Հաստատել»։")
            return
        self.db.update_request(r["request_id"], "approving", status="approved", calendar_event_id=event_id)
        self.db.upsert_session(r["patient_chat_id"], stage="confirmed", request_id=r["request_id"], updated_note="approved by doctor")
        await self.send(r["patient_chat_id"], self.confirmation_text(r), kb=[[L["myBookings"]], [L["home"], L["end"]]])
        await self.send(r["patient_chat_id"], "📍 Ինչպես հասնել կլինիկա\n\n" + "\n".join(self.clinic.info["address_lines"])
                        + "\n\nՔարտեզը կամ Ձեր գտնվելու վայրից երթուղին բացելու համար սեղմեք ստորև։",
                        inline=[[btn("🚗 Երթուղի Yandex Maps-ով", url=self.links["route"])], [btn("🗺 Կլինիկան քարտեզում", url=self.links["map"])]])
        await self.edit(r, p, msg + "\n\n✅ Հաստատված է։ Այցը ստեղծվեց օրացույցում, պացիենտը տեղեկացվել է։")
        if r["replaces_request_id"]:
            old = self.db.get_request(r["replaces_request_id"])
            if old and self.db.update_request(old["request_id"], old["status"], status="cancelled", decided_by="rescheduled"):
                if old["status"] in ("approved", "approving") and old.get("calendar_event_id"):
                    try:
                        await self.cal.delete_event(r["calendar_id"], old["calendar_event_id"])
                    except CalendarError:
                        pass

    def confirmation_text(self, r):
        lead = parse_ms(r["slot_start"]) - now_ms()
        lines = []
        if lead > 26 * HOUR:
            lines.append("• այցից 1 օր առաջ")
        if lead > 2 * HOUR:
            lines.append("• այցից 2 ժամ առաջ")
        rem = ("\n\n⏰ Մենք Ձեզ կուղարկենք հիշեցում՝\n" + "\n".join(lines)) if lines else ""
        old = re.match(r"^(\d{2})(\d{2})-(\d{2})(\d{2})-", r.get("replaces_request_id") or "")
        if r.get("replaces_request_id"):
            if old:
                y = int(r["date"][:4]) - (1 if int(old.group(1)) > int(r["date"][5:7]) else 0)
                was = f"{y}-{old.group(1)}-{old.group(2)}, {old.group(3)}:{old.group(4)}"
                head = "🔁 Ձեր այցի ժամը փոխված է։\nՁեր " + was + "-ի այցը տեղափոխվել է " + r["date"] + ", " + r["selected_time"] + " (Երևան)։\n"
            else:
                head = "🔁 Ձեր այցի ժամը փոխված է։\nՆախորդ այցը չեղարկվել է, և նոր ժամը հաստատված է։\n"
        else:
            head = "✅ Ձեր այցը հաստատված է։\n"
        body = "Այցելու՝ " + r["patient_name"] + "\nԾառայություն՝ " + r["service"] + "\nԲժիշկ՝ " + r["doctor_name"]
        if not r.get("replaces_request_id"):
            body += "\nԱմսաթիվ՝ " + r["date"] + "\nԺամ՝ " + r["selected_time"] + " (Երևան)"
        return head + body + rem + "\n\nՉեղարկելու կամ ժամը փոխելու համար սեղմեք «📋 Իմ ամրագրումները»։\nՇնորհակալություն, սպասում ենք Ձեզ։"

    async def a_reject(self, r, p):
        await self.answer(r)
        msg = p.get("message_text") or ""
        if not self.db.update_request(r["request_id"], "pending", status="rejected", decided_by=r["from_id"]):
            await self.edit(r, p, msg + "\n\nℹ️ Այս հայտն արդեն մշակված է։")
            return
        self.db.upsert_session(r["patient_chat_id"], stage="idle", request_id="", slot_options="", updated_note="rejected by doctor")
        await self.send(r["patient_chat_id"], "Ցավոք, բժիշկը չի կարող ընդունել Ձեզ " + r["date"] + " " + r["selected_time"] + "-ին։" + TRY_OTHER, kb=RETRY_KB)
        await self.edit(r, p, msg + "\n\n❌ Մերժված է։ Պացիենտը տեղեկացվել է։")

    async def a_expire(self, r, p):
        await self.answer(r)
        if not self.db.update_request(r["request_id"], "pending", status="expired", decided_by="expired_before_decision"):
            return
        self.db.update_session_if(r["patient_chat_id"], r["request_id"], request_id="", slot_options="", stage="idle", updated_note="request expired")
        await self.send(r["patient_chat_id"], "Ձեր հայտի (" + r["date"] + " " + r["selected_time"] + ") ժամկետը լրացել է, և այցը չի ստեղծվել։" + TRY_OTHER, kb=RETRY_KB)
        await self.edit(r, p, (p.get("message_text") or "") + "\n\n⌛ Հայտի ժամկետը լրացել է, այցը չի ստեղծվել։")

    async def a_deny_callback(self, r, p):
        await self.answer(r)

    # ------------------------------------------------------------------ patient bookings
    async def a_my_bookings(self, r, p):
        names = {d["doctor_key"]: d["doctor_name"] for d in self.clinic.doctors}
        now = now_ms()
        rows = sorted([x for x in self.db.requests_for_chat(r["chat_id"]) if x["status"] in ("approved", "pending") and (parse_ms(x["slot_start"]) or 0) > now],
                      key=lambda x: parse_ms(x["slot_start"]))[:5]
        if not rows:
            await self.send(r["chat_id"], "Դուք առաջիկա ակտիվ ամրագրումներ չունեք։ Նոր այց ամրագրելու համար սեղմեք «🏠 Գլխավոր մենյու»։", kb=[[L["home"], L["end"]]])
            return
        await self.send(r["chat_id"], "📋 Ձեր առաջիկա ամրագրումները՝\nՅուրաքանչյուրի տակ կարող եք չեղարկել կամ փոխել ժամը։", kb=[[L["home"], L["end"]]])
        for x in rows:
            text = ("📅 " + x["slot_start"][:10] + ", " + x["slot_start"][11:16] + " (Երևան)\nԲժիշկ՝ " + names.get(x["doctor_key"], "")
                    + "\nԾառայություն՝ " + (x["service"] or "—") + "\nԱյցելու՝ " + (x["patient_full_name"] or x["patient_name"] or "—")
                    + "\nԿարգավիճակ՝ " + ("✅ Հաստատված" if x["status"] == "approved" else "⏳ Սպասում է բժշկի հաստատմանը") + "\nՀայտ՝ " + x["request_id"])
            await self.send(r["chat_id"], text, inline=[[btn("❌ Չեղարկել", callback_data="cx|" + x["request_id"]),
                                                         btn("🔁 Փոխել ժամը", callback_data="ch|" + x["request_id"])]])

    async def a_patient_note(self, r, p):
        await self.answer(r)
        await self.edit(r, p, r["card_text"] + "\n\n" + r["text"])

    async def a_patient_cancel_ask(self, r, p):
        await self.answer(r)
        await self.edit(r, p, r["card_text"] + "\n\n❓ Իսկապե՞ս ցանկանում եք չեղարկել այս այցը։",
                        inline=[[btn("✅ Այո, չեղարկել", callback_data="cy|" + r["request_id"]), btn("↩️ Ոչ", callback_data="nx|" + r["request_id"])]])

    async def a_patient_cancel(self, r, p):
        await self.answer(r)
        if not self.db.update_request(r["request_id"], r["old_status"], decided_by="patient", status="cancelled"):
            await self.edit(r, p, r["card_text"] + "\n\nℹ️ Այս ամրագրումն այլևս ակտիվ չէ։")
            return
        if r["calendar_event_id"]:
            try:
                await self.cal.delete_event(r["calendar_id"], r["calendar_event_id"])
            except CalendarError:
                pass
        await self.edit(r, p, r["card_text"] + "\n\n❌ Այցը չեղարկված է։ Բժիշկը տեղեկացվել է։")
        await self.send(r["approver_chat_id"], "❌ Պացիենտը չեղարկեց ամրագրումը\nՀայտ՝ " + r["request_id"] + "\nՊացիենտ՝ " + r["patient_name"]
                        + (" (" + r["phone"] + ")" if r["phone"] else "") + "\nԾառայություն՝ " + r["service"] + "\nԲժիշկ՝ " + r["doctor_name"]
                        + "\nԱմսաթիվ՝ " + r["date"] + ", ժամ՝ " + r["selected_time"] + ("\nԱյցը հեռացվել է օրացույցից։" if r["calendar_event_id"] else ""))
        if r["reset_session"]:
            self.db.upsert_session(r["chat_id"], request_id="", stage="idle", updated_note="patient cancelled pending request")
        await self.notify_waitlist(r)

    async def notify_waitlist(self, r):
        """A booking was cancelled: tell waitlisted patients of this doctor (any day, or exactly this day)."""
        if not ((parse_ms(r["slot_start"]) or 0) > now_ms() + 30 * MIN):
            return
        seen, told = set(), []
        for w in self.db.waiting_for_doctor(r["doctor_key"]):
            cid = str(w["chat_id"])
            if cid == str(r["patient_chat_id"] or r["chat_id"]) or (w["wanted_date"] and w["wanted_date"] != r["date"]) or cid in seen:
                continue
            seen.add(cid)
            await self.send(cid, "🔔 Լավ լուր․ ժամ է ազատվել\nԲժիշկ՝ " + r["doctor_name"] + "\nԱմսաթիվ՝ " + r["date"] + ", ժամ՝ " + r["selected_time"]
                            + "\n\nԱմրագրելու համար սեղմեք բժշկի անունը ստորև և ընտրեք ժամը։ Ժամը կստանա առաջինը ամրագրողը։",
                            kb=[[r["doctor_name"]], [L["home"]]])
            self.db.mark_waitlist(cid, r["doctor_key"], "notified", "slot freed " + r["date"] + " " + r["selected_time"])
            told.append(w)
        # Tell the doctor / approver that waitlisted patients were told about the freed time.
        if told and r.get("approver_chat_id"):
            lines = [str(i + 1) + ". " + (w.get("patient_name") or "Անանուն պացիենտ")
                     + (" (ցանկալի օր՝ " + w["wanted_date"] + ")" if w.get("wanted_date") else "") for i, w in enumerate(told[:10])]
            await self.send(r["approver_chat_id"], "🔔 Սպասման ցուցակ\nԱզատված ժամ՝ " + r["date"] + ", " + r["selected_time"] + " · " + r["doctor_name"]
                            + "\n\nԱյս ժամի մասին տեղեկացվել է սպասման ցուցակի " + str(len(told)) + " պացիենտ՝\n" + "\n".join(lines)
                            + ("\n…" if len(told) > 10 else "")
                            + "\n\nԺամը կստանա առաջինը ամրագրողը։ Նոր հայտը կգա Ձեզ սովորական կարգով՝ հաստատելու համար։")

    async def a_change_booking(self, r, p):
        await self.answer(r)
        self.db.upsert_session(r["chat_id"], appointment_date="", doctor_key=r["doctor_key"], doctor_name=r["doctor_name"], full_name=r["full_name"],
                               phone=r["phone"], quick_rebook=r["quick_rebook"], replace_request_id=r["request_id"], selected_time="",
                               service=r["service"], slot_options="", stage="awaiting_date", updated_note="changing booking", visit_reason=r["visit_reason"])
        await self.edit(r, p, r["card_text"] + "\n\n🔁 Ընտրեք նոր ամսաթիվը ներքևի կոճակներից։ Այս ամրագրումը կչեղարկվի միայն նորի հաստատումից հետո։")
        await self.show_dates(r)

    async def a_patient_confirm(self, r, p):
        await self.answer(r)
        if self.db.update_request(r["request_id"], "approved", patient_confirmed=local_stamp(now_ms())):
            await self.edit(r, p, r["card_text"] + "\n\n" + r["text"])

    async def a_rate(self, r, p):
        await self.answer(r)
        if not self.db.update_request(r["request_id"], None, rating=r["rating"], rating_asked=True):
            return
        stars = "⭐" * r["rating"]
        if r["rating"] >= 4:
            await self.edit(r, p, r["card_text"] + "\n\n" + stars + " Շնորհակալություն բարձր գնահատականի համար։\nԵթե ունեք մեկ րոպե, կիսվեք Ձեր կարծիքով Yandex Maps-ում՝ դա շատ կօգնի այլ պացիենտներին։",
                            inline=[[btn("✍️ Թողնել կարծիք", url=self.links["reviews"])]] if self.links.get("reviews") else [])
        else:
            await self.edit(r, p, r["card_text"] + "\n\n" + stars + " Շնորհակալություն անկեղծ գնահատականի համար։\nՑավում ենք, որ ամեն ինչ չէր կատարյալ։ Կլինիկայի ադմինիստրատորը կկապվի Ձեզ հետ՝ պարզելու, թե ինչ կարող ենք բարելավել։")
            await self.send(r["approver_chat_id"], "⚠️ Ցածր գնահատական՝ " + str(r["rating"]) + "/5\nՊացիենտ՝ " + r["patient_name"] + " (" + (r["phone"] or "—")
                            + ")\nԲժիշկ՝ " + r["doctor_name"] + "\nԱյց՝ " + r["date"] + " " + r["selected_time"] + "\nՀայտ՝ " + r["request_id"]
                            + "\n\nԽորհուրդ է տրվում զանգահարել պացիենտին։")

    async def a_waitlist_join(self, r, p):
        self.db.upsert_waitlist(r["chat_id"], r["doctor_key"], doctor_name=r["doctor_name"], wanted_date=r["wl_date"],
                                patient_name=r["patient_name"], status="waiting", note="joined from bot")
        await self.a_reply(r, p)

    # ------------------------------------------------------------------ staff
    async def a_staff_menu(self, r, p):
        await self.send(r["chat_id"], r["staff_menu_text"], kb=STAFF_KB)

    async def a_staff_report(self, r, p):
        rep = build_staff_report(r, self.db.all_requests(), now_ms())
        await self.send(r["chat_id"], rep["text"], kb=STAFF_KB)
        for c in rep["cards"]:
            await self.send(r["chat_id"], c["text"], inline=[[btn("✅ Հաստատել", callback_data="ap|" + c["request_id"]),
                                                              btn("❌ Մերժել", callback_data="rj|" + c["request_id"])]])

    async def a_staff_block_ask(self, r, p):
        self.db.upsert_session(r["chat_id"], stage=r["menu_stage"], doctor_key=r["doctor_key"], appointment_date=r["date"], updated_note="staff blocking step")
        if r["block_step"] == "doctor":
            kb = rows_of(r["block_labels"], 2)
        elif r["block_step"] == "date":
            kb = rows_of(r["block_labels"], 4)
        else:
            kb = [[S["whole"]], [S["morning"], S["afternoon"]]]
        await self.send(r["chat_id"], r["text"], kb=kb + [[L["home"]]])

    async def a_staff_block_create(self, r, p):
        self.db.upsert_session(r["chat_id"], stage="idle", updated_note="staff block created")
        try:
            event_id = await self.cal.create_event(r["calendar_id"], r["slot_start"], r["slot_end"], "⛔ Փակ — " + r["doctor_name"],
                                                   "Ժամը փակել է բժիշկը / ադմինիստրատորը բոտով։ Այս ժամերը պացիենտներին չեն առաջարկվում։ "
                                                   "Բացելու համար ջնջեք այս իրադարձությունը կամ սեղմեք «Չեղարկել փակումը» բոտում։")
            await self.send(r["chat_id"], r["text"], inline=[[btn("↩️ Չեղարկել փակումը", callback_data="ub|" + r["doctor_key"] + "|" + event_id)]])
        except CalendarError:
            await self.send(r["chat_id"], "⚠️ Չհաջողվեց փակել ժամը օրացույցում։ Խնդրում ենք փորձել կրկին մի փոքր ուշ։")
        await self.a_staff_menu(r, p)

    async def a_staff_unblock(self, r, p):
        await self.answer(r)
        try:
            await self.cal.delete_event(r["calendar_id"], r["calendar_event_id"])
        except CalendarError:
            pass
        await self.edit(r, p, r["card_text"] + "\n\n↩️ Փակումը չեղարկվեց․ այս ժամերը կրկին հասանելի են պացիենտներին։")

    async def a_ignore(self, r, p):
        return
