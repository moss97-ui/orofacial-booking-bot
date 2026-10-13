"""Patient app + staff dashboard, served by the same program as the Telegram bot.

The app uses the bot's own booking engine: the same free-time rules (slots.py), the same requests table, and the same
approval flow — a booking made in the app goes to the doctor in Telegram with ✅ / ❌ buttons, and staff can also
approve it in the dashboard. App patients have chat_id "web:<account id>"; whatever the bot would send them in
Telegram is stored as an in-app notification instead (AppMessenger).

Pages:  /        patient app (installable: "Add to Home Screen")
        /admin   staff dashboard (password: ADMIN_PASSWORD)
"""
from __future__ import annotations

import hmac
import io
import logging
import os
import random
import re
import time
import uuid
from pathlib import Path

from aiohttp import web

from .actions import Bot, btn
from .appdb import AppDB, check_pin, hash_pin
from .calendar_service import CalendarError
from .router import norm_phone, valid_name
from .slots import compute_available_dates, compute_free_slots
from .texts import MONTHS, SHORT_DAYS
from .timeutil import DAY, HOUR, MIN, at, hhmm, iso_utc, now_ms, parse_ms, start_of_day_iso, start_of_month_plus, valid_date, weekday, ymd

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
STATUS = {"pending": "Սպասում է հաստատման", "approving": "Մշակվում է", "approved": "Հաստատված", "rejected": "Մերժված",
          "expired": "Ժամկետանց", "cancelled": "Չեղարկված", "conflict": "Ժամը զբաղված էր", "failed": "Չուղարկվեց"}


# ----------------------------------------------------------------------------- messages for app patients
class AppMessenger:
    """Wraps the Telegram messenger: chats "web:<id>" get in-app notifications instead of Telegram messages."""

    def __init__(self, inner, appdb: AppDB):
        self.inner, self.appdb = inner, appdb

    @staticmethod
    def web_id(chat_id):
        s = str(chat_id or "")
        return s[4:] if s.startswith("web:") else None

    async def send(self, chat_id, text, reply_kb=None, inline_kb=None, remove_kb=False) -> bool:
        wid = self.web_id(chat_id)
        if wid is not None:
            if wid.isdigit():
                self.appdb.notify(int(wid), text)
            return True
        return await self.inner.send(chat_id, text, reply_kb=reply_kb, inline_kb=inline_kb, remove_kb=remove_kb)

    async def edit(self, chat_id, message_id, text, inline_kb=None) -> bool:
        if self.web_id(chat_id) is not None:
            return True          # the app shows the new state itself
        return await self.inner.edit(chat_id, message_id, text, inline_kb=inline_kb)

    async def answer(self, callback_id, text="") -> None:
        if callback_id:
            await self.inner.answer(callback_id, text)


# ----------------------------------------------------------------------------- staff changes to prices / bios
def apply_overrides(clinic, appdb: AppDB) -> None:
    """Prices, visit lengths, bios and hours edited in the dashboard (kept in the database, applied over the config)."""
    cat = appdb.get("catalog", {}) or {}
    for r in clinic.reasons:
        o = (cat.get("reasons") or {}).get(r["key"]) or {}
        if o.get("price") is not None:
            r["price"] = str(o["price"])
        if o.get("min"):
            r["min"] = int(o["min"])
    for d in clinic.doctors:
        o = (cat.get("doctors") or {}).get(d["doctor_key"]) or {}
        for k in ("bio", "hours_text"):
            if o.get(k) is not None:
                d[k] = str(o[k])


def loyalty_rule(appdb: AppDB) -> dict:
    rule = appdb.get("loyalty", None) or {}
    return {"every": int(rule.get("every") or 10), "percent": int(rule.get("percent") or 20)}


# ----------------------------------------------------------------------------- the app
class WebApp:
    def __init__(self, bot: Bot, appdb: AppDB, uploads_dir: str | Path, admin_password: str = ""):
        self.bot, self.appdb = bot, appdb
        self.clinic, self.db = bot.clinic, bot.db
        self.uploads = Path(uploads_dir)
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.admin_password = admin_password
        self.fails: dict[str, tuple[int, float]] = {}
        self._next_cache: tuple[int, dict] | None = None
        apply_overrides(self.clinic, appdb)

    # ---------------------------------------------------------------- helpers
    def doctors(self):
        return self.clinic.active_doctors()

    def doctor(self, key):
        return next((d for d in self.doctors() if d["doctor_key"] == key), None)

    def ctx(self, d, reason_key, chat_id="") -> dict:
        """The same fields the router's doc_ctx() fills in."""
        rs = next((x for x in self.clinic.reasons_for(d) if x["key"] == reason_key), None)
        shared = len([x for x in self.doctors() if x.get("calendar_id") and x["calendar_id"] == d.get("calendar_id")]) > 1
        return {"doctor_key": d["doctor_key"], "doctor_name": d["doctor_name"], "calendar_id": d.get("calendar_id") or "",
                "approver_chat_id": str(d.get("approver_chat_id") or ""), "filter_by_name": shared,
                "duration_min": rs["min"] if rs else 30, "visit_label": rs["name"] if rs else "", "visit_reason": reason_key,
                "chat_id": chat_id, "reason": rs}

    def portrait(self, key):
        p = next((x for x in self.appdb.photos(key) if x["kind"] == "portrait"), None)
        return "/uploads/" + p["file"] if p else ""

    def ratings(self):
        rows = [x for x in self.db.all_requests() if int(x.get("rating") or 0) > 0]
        by = {}
        for x in rows:
            by.setdefault(x["doctor_key"], []).append(int(x["rating"]))
        return rows, {k: (round(sum(v) / len(v), 1), len(v)) for k, v in by.items()}

    @staticmethod
    def first_name(x):
        n = (x.get("patient_full_name") or x.get("patient_name") or "").split(" ")
        return (n[0] + (" " + n[1][0] + "." if len(n) > 1 and n[1] else "")) if n and n[0] else "Պացիենտ"

    def auth(self, request, kind="patient"):
        h = request.headers.get("Authorization", "")
        tok = self.appdb.token(h[7:] if h.startswith("Bearer ") else "")
        if not tok or tok["kind"] != kind:
            raise web.HTTPUnauthorized(text='{"error":"Մուտք գործեք նորից։"}', content_type="application/json")
        if kind == "patient":
            acc = self.appdb.account(tok["account_id"])
            if not acc:
                raise web.HTTPUnauthorized(text='{"error":"Մուտք գործեք նորից։"}', content_type="application/json")
            return acc
        return tok

    @staticmethod
    def err(status, text):
        return web.json_response({"error": text}, status=status)

    @staticmethod
    async def body(request) -> dict:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def booking_view(self, x, now):
        d = self.clinic.doctor(x["doctor_key"]) or {}
        start, end = parse_ms(x["slot_start"]) or 0, parse_ms(x["slot_end"]) or 0
        future = start > now
        return {"id": x["request_id"], "doctor": d.get("doctor_name", ""), "doctor_key": x["doctor_key"], "service": x["service"] or "",
                "date": x["slot_start"][:10], "time": x["slot_start"][11:16], "end": x["slot_end"][11:16],
                "weekday": SHORT_DAYS[weekday(x["slot_start"][:10])], "status": x["status"], "status_text": STATUS.get(x["status"], x["status"]),
                "discount": x.get("discount") or "", "future": future, "confirmed": bool(x.get("patient_confirmed")),
                "rating": int(x.get("rating") or 0), "review": x.get("review") or "",
                "can_cancel": future and x["status"] in ("approved", "pending"),
                "can_confirm": future and x["status"] == "approved" and not x.get("patient_confirmed") and start - now < 3 * DAY,
                "can_rate": x["status"] == "approved" and end and end < now and not int(x.get("rating") or 0)}

    async def callback(self, data, chat_id, from_id, request_id, card=""):
        """Run a button press through the bot's own router (same checks and messages as in Telegram)."""
        p = {"kind": "callback", "chat_id": chat_id, "from_id": from_id, "username": "", "callback_id": "", "data": data, "text": "",
             "first_name": "", "lookup_request_id": request_id, "message_id": 0, "message_text": card, "contact_phone": "",
             "contact_user_id": ""}
        await self.bot.handle_update(p)
        return self.db.get_request(request_id)

    async def events(self, d, start_iso, end_iso):
        return await self.bot.cal.list_events(d.get("calendar_id") or "", start_iso, end_iso)

    # ---------------------------------------------------------------- public: clinic, free times, reviews, photos
    async def h_clinic(self, request):
        c = self.clinic.info
        _, avg = self.ratings()
        docs = []
        for d in self.doctors():
            a = avg.get(d["doctor_key"])
            docs.append({"key": d["doctor_key"], "name": d["doctor_name"], "specialty": d["specialty"],
                         "specialty_name": self.clinic.service_name(d["specialty"]), "bio": d.get("bio") or "",
                         "hours": d.get("hours_text") or "", "photo": self.portrait(d["doctor_key"]),
                         "rating": a[0] if a else None, "ratings": a[1] if a else 0,
                         "reasons": [{"key": r["key"], "label": r["label"], "name": r["name"], "min": r["min"], "price": r["price"]}
                                     for r in self.clinic.reasons_for(d)]})
        services = [{"key": r["key"], "label": r["label"], "name": r["name"], "min": r["min"], "price": r["price"],
                     "doctors": [d["doctor_key"] for d in self.doctors() if d["specialty"] in r["specialties"]]} for r in self.clinic.reasons]
        lr = loyalty_rule(self.appdb)
        return web.json_response({
            "name": c.get("name"), "full_name": c.get("full_name") or c.get("name"), "phone": c.get("phone"), "mobile": c.get("mobile"),
            "hours": c.get("hours_text"), "address": c.get("address_short"), "address_lines": c.get("address_lines") or [],
            "links": c.get("links") or {}, "price_note": self.clinic.price_note, "doctors": docs, "services": services,
            "loyalty": lr, "admin_enabled": bool(self.admin_password)})

    async def first_free(self, d, reason_key, now):
        r = self.ctx(d, reason_key)
        try:
            events = await self.events(d, start_of_day_iso(now), start_of_month_plus(now, 2))
        except CalendarError:
            return None
        holds = self.db.requests_for_doctor(d["doctor_key"])
        for off in (0, 1):
            res = compute_available_dates({**r, "month_offset": off}, events, holds, self.clinic, now)
            for day in res.get("days") or []:
                s = compute_free_slots({**r, "date": day["date"], "mode": "date"}, events, self.db.requests_for_doctor(d["doctor_key"], day["date"]),
                                       self.clinic, now)
                if s["free"]:
                    return {"date": day["date"], "time": s["free"][0]}
        return None

    async def h_next_free(self, request):
        now = now_ms()
        key = now // (60 * 1000)
        if self._next_cache and self._next_cache[0] == key:
            return web.json_response(self._next_cache[1])
        per = []
        for d in self.doctors():
            rs = self.clinic.reasons_for(d)
            if not rs or not d.get("calendar_id"):
                continue
            first = min(rs, key=lambda x: x["min"])
            f = await self.first_free(d, first["key"], now)
            if f:
                per.append({"doctor": d["doctor_key"], "doctor_name": d["doctor_name"], "reason": first["key"], "reason_label": first["label"],
                            "date": f["date"], "time": f["time"], "weekday": SHORT_DAYS[weekday(f["date"])]})
        per.sort(key=lambda x: (x["date"], x["time"]))
        out = {"best": per[0] if per else None, "doctors": per, "today": ymd(now)}
        self._next_cache = (key, out)
        return web.json_response(out)

    def req_doctor_reason(self, q):
        d = self.doctor(q.get("doctor", ""))
        if not d:
            raise web.HTTPBadRequest(text='{"error":"Բժիշկը չի գտնվել։"}', content_type="application/json")
        rs = next((x for x in self.clinic.reasons_for(d) if x["key"] == q.get("reason")), None)
        if not rs:
            raise web.HTTPBadRequest(text='{"error":"Ընտրեք այցի նպատակը։"}', content_type="application/json")
        return d, rs

    def chat_of(self, request):
        h = request.headers.get("Authorization", "")
        tok = self.appdb.token(h[7:] if h.startswith("Bearer ") else "")
        return "web:" + str(tok["account_id"]) if tok and tok["kind"] == "patient" else ""

    async def h_dates(self, request):
        d, rs = self.req_doctor_reason(request.query)
        now = now_ms()
        r = self.ctx(d, rs["key"], self.chat_of(request))
        try:
            events = await self.events(d, start_of_day_iso(now), start_of_month_plus(now, 2))
        except CalendarError:
            return self.err(503, "Օրացույցը հիմա հասանելի չէ։ Փորձեք մի փոքր ուշ։")
        holds = self.db.requests_for_doctor(d["doctor_key"])
        months = []
        for off in (0, 1):
            res = compute_available_dates({**r, "month_offset": off}, events, holds, self.clinic, now)
            m0 = int(ymd(now)[5:7]) - 1 + off
            months.append({"key": res.get("month_key"), "name": MONTHS[m0 % 12],
                           "days": [{"date": x["date"], "free": x["free"], "weekday": SHORT_DAYS[weekday(x["date"])]} for x in res.get("days") or []]})
        return web.json_response({"months": months, "today": ymd(now)})

    async def h_slots(self, request):
        d, rs = self.req_doctor_reason(request.query)
        day = request.query.get("date", "")
        if not valid_date(day):
            return self.err(400, "Ընտրեք օրը։")
        r = self.ctx(d, rs["key"], self.chat_of(request))
        try:
            events = await self.events(d, day + "T00:00:00+04:00", ymd(at(day, "12:00") + DAY) + "T00:00:00+04:00")
        except CalendarError:
            return self.err(503, "Օրացույցը հիմա հասանելի չէ։ Փորձեք մի փոքր ուշ։")
        res = compute_free_slots({**r, "date": day, "mode": "date"}, events, self.db.requests_for_doctor(d["doctor_key"], day), self.clinic, now_ms())
        return web.json_response({"date": day, "times": res["free"], "minutes": rs["min"]})

    async def h_reviews(self, request):
        rows, avg = self.ratings()
        good = sorted([x for x in rows if int(x["rating"]) >= 4 and (x.get("review") or "").strip()], key=lambda x: x["updatedAt"] or "", reverse=True)
        allr = [int(x["rating"]) for x in rows]
        return web.json_response({
            "average": round(sum(allr) / len(allr), 1) if allr else None, "count": len(allr),
            "reviews": [{"name": self.first_name(x), "stars": int(x["rating"]), "text": x["review"], "doctor": (self.clinic.doctor(x["doctor_key"]) or {}).get("doctor_name", ""),
                         "date": x["slot_start"][:10]} for x in good[:30]]})

    async def h_photos(self, request):
        return web.json_response([{"id": p["id"], "url": "/uploads/" + p["file"], "caption": p["caption"], "doctor": p["doctor_key"], "kind": p["kind"]}
                                  for p in self.appdb.photos() if p["kind"] != "portrait"])

    async def h_promo_check(self, request):
        b = await self.body(request)
        p = self.appdb.usable_promo(b.get("code", ""))
        if not p:
            return self.err(404, "Այս պրոմոկոդը վավեր չէ։")
        return web.json_response({"code": p["code"], "percent": p["percent"], "note": p["note"]})

    # ---------------------------------------------------------------- patient accounts
    async def h_auth(self, request):
        b = await self.body(request)
        phone = norm_phone(b.get("phone", ""))
        pin = str(b.get("pin", "")).strip()
        if not phone:
            return self.err(400, "Գրեք ճիշտ հեռախոսահամար, օրինակ՝ 091 123456։")
        if not re.fullmatch(r"\d{4,6}", pin):
            return self.err(400, "PIN-ը պետք է լինի 4–6 թիվ։")
        fails, until = self.fails.get(phone, (0, 0.0))
        if until > time.time():
            return self.err(429, "Չափազանց շատ փորձեր։ Փորձեք 15 րոպեից։")
        acc = self.appdb.account_by_phone(phone)
        created = False
        if acc:
            if not check_pin(pin, acc["pin_hash"]):
                fails += 1
                self.fails[phone] = (fails, time.time() + 15 * 60 if fails >= 5 else 0.0)
                return self.err(401, "PIN-ը սխալ է։" + (" Մնաց " + str(5 - fails) + " փորձ։" if fails < 5 else ""))
        else:
            name = re.sub(r"\s+", " ", str(b.get("name", ""))).strip()
            if not valid_name(name):
                return self.err(400, "Առաջին մուտքի համար գրեք Ձեր անունը և ազգանունը, օրինակ՝ Անի Պետրոսյան։")
            acc = self.appdb.create_account(phone, name, pin)
            created = True
        self.fails.pop(phone, None)
        return web.json_response({"token": self.appdb.new_token("patient", acc["id"]), "created": created,
                                  "account": {"name": acc["name"], "phone": acc["phone"]}})

    async def h_logout(self, request):
        h = request.headers.get("Authorization", "")
        self.appdb.drop_token(h[7:] if h.startswith("Bearer ") else "")
        return web.json_response({"ok": True})

    def loyalty_of(self, chat_id, now):
        visits = [x for x in self.db.requests_for_chat(chat_id) if x["status"] == "approved" and (parse_ms(x["slot_end"]) or 0) < now]
        rule = loyalty_rule(self.appdb)
        n = len(visits)
        return {"visits": n, "every": rule["every"], "percent": rule["percent"], "in_cycle": n % rule["every"],
                "next_is_reward": (n + 1) % rule["every"] == 0}

    async def h_me(self, request):
        acc = self.auth(request)
        now = now_ms()
        chat = "web:" + str(acc["id"])
        rows = sorted(self.db.requests_for_chat(chat), key=lambda x: x["slot_start"] or "")
        views = [self.booking_view(x, now) for x in rows if x["status"] not in ("conflict", "failed")]
        unread = len([n for n in self.appdb.notifications(acc["id"]) if not n["read"]])
        return web.json_response({"name": acc["name"], "phone": acc["phone"], "favourite": acc["favourite"],
                                  "upcoming": [v for v in views if v["future"] and v["status"] in ("approved", "pending", "approving")],
                                  "past": list(reversed([v for v in views if not (v["future"] and v["status"] in ("approved", "pending", "approving"))]))[:30],
                                  "loyalty": self.loyalty_of(chat, now), "unread": unread})

    async def h_me_update(self, request):
        acc = self.auth(request)
        b = await self.body(request)
        fields = {}
        if "name" in b:
            name = re.sub(r"\s+", " ", str(b["name"])).strip()
            if not valid_name(name):
                return self.err(400, "Գրեք անունը և ազգանունը տառերով։")
            fields["name"] = name
        if "favourite" in b:
            fields["favourite"] = b["favourite"] if self.doctor(b["favourite"]) else ""
        if "pin" in b:
            if not re.fullmatch(r"\d{4,6}", str(b["pin"])):
                return self.err(400, "PIN-ը պետք է լինի 4–6 թիվ։")
            fields["pin_hash"] = hash_pin(str(b["pin"]))
        self.appdb.update_account(acc["id"], **fields)
        return web.json_response({"ok": True})

    async def h_notifications(self, request):
        acc = self.auth(request)
        return web.json_response([{"id": n["id"], "text": n["text"], "read": bool(n["read"]), "at": n["createdAt"]} for n in self.appdb.notifications(acc["id"])])

    async def h_notifications_read(self, request):
        acc = self.auth(request)
        self.appdb.mark_read(acc["id"])
        return web.json_response({"ok": True})

    # ---------------------------------------------------------------- booking from the app
    async def h_book(self, request):
        acc = self.auth(request)
        b = await self.body(request)
        d, rs = self.req_doctor_reason(b)
        day, hm = str(b.get("date", "")), str(b.get("time", ""))
        now = now_ms()
        if not valid_date(day) or not re.fullmatch(r"\d\d:\d\d", hm):
            return self.err(400, "Ընտրեք օրը և ժամը։")
        if day > ymd(now + int(self.clinic.booking["max_days_ahead"]) * DAY):
            return self.err(400, "Ամրագրումը հնարավոր է առավելագույնը 2 ամիս առաջ։")
        if not d.get("approver_chat_id") or str(d["approver_chat_id"]).startswith("REPLACE"):
            return self.err(409, "Այս բժշկի հաստատման կապը դեռ կարգավորված չէ։ Ընտրեք այլ բժշկի։")
        chat = "web:" + str(acc["id"])
        r = self.ctx(d, rs["key"], chat)
        try:
            events = await self.events(d, day + "T00:00:00+04:00", ymd(at(day, "12:00") + DAY) + "T00:00:00+04:00")
        except CalendarError:
            return self.err(503, "Օրացույցը հիմա հասանելի չէ։ Փորձեք մի փոքր ուշ։")
        res = compute_free_slots({**r, "date": day, "mode": "time", "selected_time": hm}, events,
                                 self.db.requests_for_doctor(d["doctor_key"], day), self.clinic, now)
        if not res["ok"]:
            return self.err(409, "Այս ժամն այլևս ազատ չէ։ Ընտրեք այլ ժամ։")
        # Discount: a promo code, or the loyalty reward on every N-th visit (the bigger one).
        promo = self.appdb.usable_promo(b.get("promo", "")) if b.get("promo") else None
        if b.get("promo") and not promo:
            return self.err(400, "Այս պրոմոկոդը վավեր չէ։")
        loyal = self.loyalty_of(chat, now)
        disc, why = 0, ""
        if promo:
            disc, why = int(promo["percent"]), "պրոմոկոդ " + promo["code"]
        if loyal["next_is_reward"] and loyal["percent"] > disc:
            disc, why = loyal["percent"], str(loyal["every"]) + "-րդ այց"
        start_ms = at(day, hm)
        slot_start = day + "T" + hm + ":00+04:00"
        slot_end = day + "T" + hhmm(start_ms + rs["min"] * MIN) + ":00+04:00"
        rid = day[5:7] + day[8:10] + "-" + hm.replace(":", "") + "-" + str(random.randint(100, 999))
        while self.db.get_request(rid):
            rid = rid[:-3] + str(random.randint(100, 999))
        exp = min(now + float(self.clinic.booking["request_ttl_hours"]) * HOUR, start_ms)
        msg = ("🦷 Նոր ամրագրման հայտ (📱 հավելվածից)\nՀայտ՝ " + rid + "\nՊացիենտ՝ " + acc["name"] + "\nՀեռախոս՝ " + acc["phone"]
               + "\nԾառայություն՝ " + rs["name"] + "\nԲժիշկ՝ " + d["doctor_name"] + "\nԱմսաթիվ՝ " + day + "\nԺամ՝ " + hm + "–" + slot_end[11:16] + " (Երևան)"
               + (("\n🎁 Զեղչ՝ −" + str(disc) + "% (" + why + ")") if disc else "")
               + "\nՀայտը վավեր է մինչև " + ymd(int(exp)) + " " + hhmm(int(exp)) + "։")
        self.db.insert_request({
            "request_id": rid, "chat_id": chat, "patient_name": acc["name"], "patient_full_name": acc["name"], "patient_phone": acc["phone"],
            "telegram_username": "", "doctor_key": d["doctor_key"], "service": rs["name"], "slot_start": slot_start, "slot_end": slot_end,
            "slot_key": d["doctor_key"] + "|" + slot_start, "status": "pending", "expires_at": iso_utc(int(exp)), "replaces_request_id": "",
            "source": "app", "promo": promo["code"] if promo else "", "discount": (str(disc) + "% · " + why) if disc else ""})
        # Two people could pick overlapping times at the same moment: the request saved first keeps the time.
        active = []
        for x in self.db.requests_for_doctor(d["doctor_key"], day):
            st = x["status"]
            if st in ("approving", "approved") or (st == "pending" and (parse_ms(x["expires_at"]) or 0) > now):
                a = parse_ms(x["slot_start"]); e = parse_ms(x["slot_end"]) or a + 30 * MIN
                if a < parse_ms(slot_end) and e > parse_ms(slot_start):
                    active.append(x)
        active.sort(key=lambda x: x["id"])
        if not active or active[0]["request_id"] != rid:
            self.db.update_request(rid, "pending", status="conflict", decided_by="slot_taken")
            return self.err(409, "Այս ժամը հենց նոր ամրագրվեց։ Ընտրեք այլ ժամ։")
        sent = await self.bot.send(d["approver_chat_id"], msg, inline=[[btn("✅ Հաստատել", callback_data="ap|" + rid),
                                                                       btn("❌ Մերժել", callback_data="rj|" + rid)]])
        if not sent:
            self.db.update_request(rid, "pending", status="failed", decided_by="doctor_unreachable")
            return self.err(502, "Չհաջողվեց հայտը փոխանցել բժշկին։ Փորձեք մի փոքր ուշ կամ զանգահարեք կլինիկա։")
        if promo:
            self.appdb.use_promo(promo["code"])
        if not acc["favourite"]:
            self.appdb.update_account(acc["id"], favourite=d["doctor_key"])
        self.appdb.notify(acc["id"], "📨 Ձեր հայտն ուղարկվեց բժշկին՝ " + d["doctor_name"] + "\n" + rs["name"] + "\n" + day + ", " + hm
                          + "\nԲժշկի պատասխանը կտեսնեք այստեղ։")
        self._next_cache = None
        return web.json_response({"ok": True, "id": rid, "discount": disc, "why": why})

    def own(self, acc, rid):
        x = self.db.get_request(rid)
        if not x or x["chat_id"] != "web:" + str(acc["id"]):
            raise web.HTTPNotFound(text='{"error":"Ամրագրումը չի գտնվել։"}', content_type="application/json")
        return x

    async def h_cancel(self, request):
        acc = self.auth(request)
        x = self.own(acc, request.match_info["rid"])
        chat = "web:" + str(acc["id"])
        x = await self.callback("cy|" + x["request_id"], chat, chat, x["request_id"])
        self._next_cache = None
        return web.json_response({"ok": x["status"] == "cancelled", "status": x["status"]})

    async def h_confirm(self, request):
        acc = self.auth(request)
        x = self.own(acc, request.match_info["rid"])
        chat = "web:" + str(acc["id"])
        x = await self.callback("ok|" + x["request_id"], chat, chat, x["request_id"])
        return web.json_response({"ok": bool(x.get("patient_confirmed"))})

    async def h_rate(self, request):
        acc = self.auth(request)
        x = self.own(acc, request.match_info["rid"])
        b = await self.body(request)
        stars = int(b.get("stars") or 0)
        if stars < 1 or stars > 5:
            return self.err(400, "Ընտրեք 1-ից 5 աստղ։")
        chat = "web:" + str(acc["id"])
        x = await self.callback("r" + str(stars) + "|" + x["request_id"], chat, chat, x["request_id"])
        if int(x.get("rating") or 0) == stars:
            self.db.update_request(x["request_id"], None, review=str(b.get("review") or "").strip()[:600])
            return web.json_response({"ok": True})
        return self.err(409, "Այս այցը հնարավոր չէ գնահատել։")

    # ---------------------------------------------------------------- staff dashboard
    async def h_admin_login(self, request):
        if not self.admin_password:
            return self.err(503, "Վահանակը միացված չէ․ Railway-ում ավելացրեք ADMIN_PASSWORD փոփոխականը։")
        b = await self.body(request)
        fails, until = self.fails.get("admin", (0, 0.0))
        if until > time.time():
            return self.err(429, "Չափազանց շատ փորձեր։ Փորձեք 15 րոպեից։")
        if not hmac.compare_digest(str(b.get("password", "")).encode(), self.admin_password.encode()):
            fails += 1
            self.fails["admin"] = (fails, time.time() + 15 * 60 if fails >= 5 else 0.0)
            return self.err(401, "Գաղտնաբառը սխալ է։")
        self.fails.pop("admin", None)
        return web.json_response({"token": self.appdb.new_token("admin")})

    def admin_row(self, x, now):
        v = self.booking_view(x, now)
        v.update(patient=x.get("patient_full_name") or x.get("patient_name") or "", phone=x.get("patient_phone") or "",
                 source="app" if x.get("source") == "app" else "telegram", promo=x.get("promo") or "")
        return v

    async def h_admin_overview(self, request):
        self.auth(request, "admin")
        now = now_ms()
        today = ymd(now)
        rows = self.db.all_requests()
        live = [x for x in rows if x["status"] in ("approved", "pending", "approving")]
        todays = sorted([x for x in live if x["slot_start"][:10] == today], key=lambda x: x["slot_start"])
        week = [x for x in live if today <= x["slot_start"][:10] <= ymd(now + 6 * DAY)]
        pending = sorted([x for x in rows if x["status"] == "pending" and (parse_ms(x["expires_at"]) or 0) > now], key=lambda x: x["slot_start"])
        ratings = [int(x["rating"]) for x in rows if int(x.get("rating") or 0)]
        month = [x for x in rows if x["createdAt"] and x["createdAt"][:7] == today[:7] and x["status"] not in ("conflict", "failed")]
        return web.json_response({
            "today": [self.admin_row(x, now) for x in todays], "pending": [self.admin_row(x, now) for x in pending],
            "stats": {"today": len(todays), "week": len(week), "pending": len(pending), "accounts": self.appdb.count_accounts(),
                      "rating": round(sum(ratings) / len(ratings), 1) if ratings else None, "ratings": len(ratings),
                      "month_requests": len(month), "month_app": len([x for x in month if x.get("source") == "app"])}})

    async def h_admin_bookings(self, request):
        self.auth(request, "admin")
        now = now_ms()
        start = request.query.get("from") or ymd(now)
        days = max(1, min(31, int(request.query.get("days") or 7)))
        if not valid_date(start):
            return self.err(400, "Սխալ ամսաթիվ։")
        end = ymd(at(start, "12:00") + (days - 1) * DAY)
        rows = sorted([x for x in self.db.all_requests() if start <= (x["slot_start"] or "")[:10] <= end
                       and x["status"] in ("approved", "pending", "approving", "cancelled", "rejected")], key=lambda x: x["slot_start"])
        doc = request.query.get("doctor")
        if doc:
            rows = [x for x in rows if x["doctor_key"] == doc]
        return web.json_response({"from": start, "to": end, "bookings": [self.admin_row(x, now) for x in rows]})

    async def h_admin_decide(self, request):
        self.auth(request, "admin")
        rid, verb = request.match_info["rid"], request.match_info["verb"]
        x = self.db.get_request(rid)
        if not x:
            return self.err(404, "Հայտը չի գտնվել։")
        d = self.clinic.doctor(x["doctor_key"]) or {}
        approver = str(d.get("approver_chat_id") or "")
        card = "Հայտ " + rid + " (վահանակից)"
        x = await self.callback(("ap|" if verb == "approve" else "rj|") + rid, "web:admin", approver, rid, card)
        self._next_cache = None
        want = "approved" if verb == "approve" else "rejected"
        if x["status"] != want:
            return self.err(409, "Չհաջողվեց․ հայտի կարգավիճակը՝ " + STATUS.get(x["status"], x["status"]) + "։")
        return web.json_response({"ok": True, "status": x["status"]})

    async def h_admin_blocks(self, request):
        self.auth(request, "admin")
        now = now_ms()
        out = []
        for d in self.doctors():
            try:
                events = await self.events(d, start_of_day_iso(now), start_of_month_plus(now, 2))
            except CalendarError:
                continue
            for e in events:
                if str(e.get("summary") or "").startswith("⛔") and d["doctor_name"] in str(e.get("summary") or "") and e.get("status") != "cancelled":
                    s, en = e.get("start") or {}, e.get("end") or {}
                    out.append({"doctor": d["doctor_key"], "doctor_name": d["doctor_name"], "id": e["id"],
                                "start": s.get("dateTime") or s.get("date"), "end": en.get("dateTime") or en.get("date")})
        return web.json_response(sorted(out, key=lambda x: x["start"] or ""))

    async def h_admin_block(self, request):
        self.auth(request, "admin")
        b = await self.body(request)
        d = self.doctor(b.get("doctor", ""))
        day, a, z = str(b.get("date", "")), str(b.get("from") or "00:00"), str(b.get("to") or "23:59")
        if not d or not valid_date(day) or not re.fullmatch(r"\d\d:\d\d", a) or not re.fullmatch(r"\d\d:\d\d", z) or z <= a:
            return self.err(400, "Ընտրեք բժշկին, օրը և ճիշտ ժամային միջակայքը։")
        try:
            eid = await self.bot.cal.create_event(d.get("calendar_id") or "", day + "T" + a + ":00+04:00", day + "T" + z + ":00+04:00",
                                                  "⛔ Փակ — " + d["doctor_name"], "Փակվել է վահանակից։ Այս ժամերը պացիենտներին չեն առաջարկվում։")
        except CalendarError:
            return self.err(503, "Չհաջողվեց փակել ժամը օրացույցում։")
        self._next_cache = None
        return web.json_response({"ok": True, "id": eid})

    async def h_admin_unblock(self, request):
        self.auth(request, "admin")
        d = self.doctor(request.match_info["doctor"])
        if not d:
            return self.err(404, "Բժիշկը չի գտնվել։")
        try:
            await self.bot.cal.delete_event(d.get("calendar_id") or "", request.match_info["eid"])
        except CalendarError:
            return self.err(503, "Չհաջողվեց բացել ժամը։")
        self._next_cache = None
        return web.json_response({"ok": True})

    async def h_admin_catalog(self, request):
        self.auth(request, "admin")
        return web.json_response({
            "reasons": [{"key": r["key"], "label": r["label"], "name": r["name"], "min": r["min"], "price": r["price"]} for r in self.clinic.reasons],
            "doctors": [{"key": d["doctor_key"], "name": d["doctor_name"], "bio": d.get("bio") or "", "hours": d.get("hours_text") or "",
                         "photo": self.portrait(d["doctor_key"])} for d in self.doctors()],
            "loyalty": loyalty_rule(self.appdb)})

    async def h_admin_catalog_save(self, request):
        self.auth(request, "admin")
        b = await self.body(request)
        cat = self.appdb.get("catalog", {}) or {}
        keys = {r["key"] for r in self.clinic.reasons}
        for k, v in (b.get("reasons") or {}).items():
            if k in keys and isinstance(v, dict):
                o = cat.setdefault("reasons", {}).setdefault(k, {})
                if "price" in v:
                    o["price"] = str(v["price"])[:40]
                if v.get("min"):
                    m = int(v["min"])
                    if m < 15 or m > 240 or m % 15:
                        return self.err(400, "Տևողությունը պետք է լինի 15-ից 240 րոպե՝ 15-ի բազմապատիկ։")
                    o["min"] = m
        dkeys = {d["doctor_key"] for d in self.clinic.doctors}
        for k, v in (b.get("doctors") or {}).items():
            if k in dkeys and isinstance(v, dict):
                o = cat.setdefault("doctors", {}).setdefault(k, {})
                if "bio" in v:
                    o["bio"] = str(v["bio"])[:800]
                if "hours" in v:
                    o["hours_text"] = str(v["hours"])[:80]
        self.appdb.put("catalog", cat)
        if isinstance(b.get("loyalty"), dict):
            every, pct = int(b["loyalty"].get("every") or 10), int(b["loyalty"].get("percent") or 20)
            if not (2 <= every <= 50 and 1 <= pct <= 100):
                return self.err(400, "Հավատարմության կանոնը սխալ է։")
            self.appdb.put("loyalty", {"every": every, "percent": pct})
        apply_overrides(self.clinic, self.appdb)
        self._next_cache = None
        return web.json_response({"ok": True})

    async def h_admin_promos(self, request):
        self.auth(request, "admin")
        return web.json_response([{k: p[k] for k in ("code", "percent", "note", "active", "max_uses", "uses")} for p in self.appdb.promos()])

    async def h_admin_promo_save(self, request):
        self.auth(request, "admin")
        b = await self.body(request)
        code = str(b.get("code", "")).strip().upper()
        if not re.fullmatch(r"[A-Z0-9Ա-Ֆ\-]{3,20}", code):
            return self.err(400, "Կոդը՝ 3–20 տառ կամ թիվ, առանց բացատի։")
        pct = int(b.get("percent") or 0)
        if not 1 <= pct <= 100:
            return self.err(400, "Զեղչը՝ 1-ից 100 տոկոս։")
        self.appdb.save_promo(code, pct, str(b.get("note", ""))[:120], int(b.get("max_uses") or 0), bool(b.get("active", True)))
        return web.json_response({"ok": True})

    async def h_admin_promo_delete(self, request):
        self.auth(request, "admin")
        self.appdb.delete_promo(request.match_info["code"])
        return web.json_response({"ok": True})

    async def h_admin_photo_upload(self, request):
        self.auth(request, "admin")
        form = await request.post()
        f = form.get("file")
        if f is None or not hasattr(f, "file"):
            return self.err(400, "Ընտրեք լուսանկար։")
        raw = f.file.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            return self.err(400, "Լուսանկարը չափազանց մեծ է (առավելագույնը 8 ՄԲ)։")
        try:
            from PIL import Image, ImageOps
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
            img = img.convert("RGB")
            img.thumbnail((1600, 1600))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=84, optimize=True)
        except Exception:
            return self.err(400, "Սա լուսանկար չէ կամ ֆորմատը չի աջակցվում (JPEG, PNG, WebP, HEIC չի աջակցվում)։")
        kind = form.get("kind") if form.get("kind") in ("portrait", "work", "clinic") else "work"
        doc = form.get("doctor") or ""
        if doc and not self.doctor(doc):
            doc = ""
        if kind == "portrait" and not doc:
            return self.err(400, "Դիմանկարի համար ընտրեք բժշկին։")
        name = uuid.uuid4().hex + ".jpg"
        (self.uploads / name).write_bytes(buf.getvalue())
        pid = self.appdb.add_photo(doc, kind, name, str(form.get("caption") or "")[:140])
        return web.json_response({"ok": True, "id": pid, "url": "/uploads/" + name})

    async def h_admin_photos(self, request):
        self.auth(request, "admin")
        return web.json_response([{"id": p["id"], "url": "/uploads/" + p["file"], "caption": p["caption"], "doctor": p["doctor_key"], "kind": p["kind"]}
                                  for p in self.appdb.photos()])

    async def h_admin_photo_delete(self, request):
        self.auth(request, "admin")
        p = self.appdb.photo(request.match_info["pid"])
        if p:
            self.appdb.delete_photo(p["id"])
            try:
                (self.uploads / p["file"]).unlink()
            except OSError:
                pass
        return web.json_response({"ok": True})

    async def h_admin_reviews(self, request):
        self.auth(request, "admin")
        rows, avg = self.ratings()
        rows = sorted(rows, key=lambda x: x["updatedAt"] or "", reverse=True)
        return web.json_response({"doctors": [{"key": k, "name": (self.clinic.doctor(k) or {}).get("doctor_name", k), "average": v[0], "count": v[1]}
                                              for k, v in avg.items()],
                                  "reviews": [{"name": x.get("patient_full_name") or x.get("patient_name"), "phone": x.get("patient_phone"),
                                               "stars": int(x["rating"]), "text": x.get("review") or "", "date": x["slot_start"][:10],
                                               "doctor": (self.clinic.doctor(x["doctor_key"]) or {}).get("doctor_name", "")} for x in rows[:100]]})

    # ---------------------------------------------------------------- pages and files
    async def h_index(self, request):
        return web.FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    async def h_admin_page(self, request):
        return web.FileResponse(WEB_DIR / "admin.html", headers={"Cache-Control": "no-cache"})

    async def h_upload(self, request):
        name = request.match_info["name"]
        if not re.fullmatch(r"[0-9a-f]{32}\.jpg", name) or not (self.uploads / name).exists():
            raise web.HTTPNotFound()
        return web.FileResponse(self.uploads / name, headers={"Cache-Control": "public, max-age=604800"})

    async def h_sw(self, request):
        # served from the root so it controls the whole app
        return web.FileResponse(WEB_DIR / "sw.js", headers={"Cache-Control": "no-cache", "Content-Type": "text/javascript"})

    async def h_health(self, request):
        return web.json_response({"ok": True})

    def build(self) -> web.Application:
        @web.middleware
        async def headers(request, handler):
            resp = await handler(request)
            resp.headers.setdefault("X-Content-Type-Options", "nosniff")
            resp.headers.setdefault("Referrer-Policy", "same-origin")
            resp.headers.setdefault("X-Frame-Options", "DENY")
            return resp

        app = web.Application(middlewares=[headers], client_max_size=9 * 1024 * 1024)
        g, p, dl = app.router.add_get, app.router.add_post, app.router.add_delete
        g("/", self.h_index); g("/admin", self.h_admin_page); g("/health", self.h_health); g("/sw.js", self.h_sw)
        g("/uploads/{name}", self.h_upload)
        g("/api/clinic", self.h_clinic); g("/api/next-free", self.h_next_free); g("/api/dates", self.h_dates); g("/api/slots", self.h_slots)
        g("/api/reviews", self.h_reviews); g("/api/photos", self.h_photos); p("/api/promo/check", self.h_promo_check)
        p("/api/auth", self.h_auth); p("/api/logout", self.h_logout)
        g("/api/me", self.h_me); p("/api/me", self.h_me_update)
        g("/api/notifications", self.h_notifications); p("/api/notifications/read", self.h_notifications_read)
        p("/api/book", self.h_book)
        p("/api/bookings/{rid}/cancel", self.h_cancel); p("/api/bookings/{rid}/confirm", self.h_confirm); p("/api/bookings/{rid}/rate", self.h_rate)
        p("/api/admin/login", self.h_admin_login); g("/api/admin/overview", self.h_admin_overview); g("/api/admin/bookings", self.h_admin_bookings)
        p("/api/admin/bookings/{rid}/{verb:approve|reject}", self.h_admin_decide)
        g("/api/admin/blocks", self.h_admin_blocks); p("/api/admin/blocks", self.h_admin_block); dl("/api/admin/blocks/{doctor}/{eid}", self.h_admin_unblock)
        g("/api/admin/catalog", self.h_admin_catalog); p("/api/admin/catalog", self.h_admin_catalog_save)
        g("/api/admin/promos", self.h_admin_promos); p("/api/admin/promos", self.h_admin_promo_save); dl("/api/admin/promos/{code}", self.h_admin_promo_delete)
        g("/api/admin/photos", self.h_admin_photos); p("/api/admin/photos", self.h_admin_photo_upload); dl("/api/admin/photos/{pid}", self.h_admin_photo_delete)
        g("/api/admin/reviews", self.h_admin_reviews)
        app.router.add_static("/static/", WEB_DIR, show_index=False)
        return app
