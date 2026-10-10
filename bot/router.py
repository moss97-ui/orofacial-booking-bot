"""Decides what to do with one Telegram update. Pure logic: no Telegram, database or calendar calls.

Input:  p   – the parsed update (see main.parse_update)
        s   – the chat's saved session row ({} if none)
        req – the booking request referenced by a button tap (or None)
Output: an `out` dict whose `action` tells actions.py what to do, plus the data it needs.
This is a direct port of the n8n "Route" Code node.
"""
from __future__ import annotations

import json
import random
import re

from .clinic import Clinic
from .texts import HOME, L, MON, MONTHS, S, SHORT_DAYS, STATUS_HY
from .timeutil import DAY, HOUR, MIN, at, hhmm, iso_utc, parse_ms, valid_date, weekday, ymd

NO_APPROVER = "Ներողություն, այս բժշկի հաստատման կապը դեռ կարգավորված չէ, ուստի հայտ ուղարկել հնարավոր չէ։ Ընտրեք այլ բժշկի կամ փորձեք ավելի ուշ։"
RESTART_MSG = "Խնդրում ենք սկսել նորից՝ սեղմելով " + HOME + "։"

STAFF_GUIDE = ("📖 Ուղեցույց բժշկի / ադմինիստրատորի համար\n\n"
               "1️⃣ Նոր հայտ\nԵրբ պացիենտը ժամ է ընտրում, Դուք ստանում եք հաղորդագրություն՝ անուն, հեռախոս, բժիշկ, օր և ժամ։\n\n"
               "2️⃣ Հաստատել կամ մերժել\nՍեղմեք հաղորդագրության տակի կոճակը․\n✅ Հաստատել — այցը կավելանա օրացույցում, պացիենտը կստանա հաստատում և հիշեցումներ։\n❌ Մերժել — պացիենտին կառաջարկվի ընտրել այլ օր կամ ժամ։\n\n"
               "3️⃣ Մենյուի կոճակները\n🚫 Փակել օր / ժամ — արձակուրդ, ընդմիջում կամ զբաղված ժամ․ այդ ժամերը պացիենտներին չեն առաջարկվի\n📊 Վահանակ — ամփոփ պատկեր մեկ հայացքով\n📅 Այսօրվա այցերը — այսօրվա ցուցակը\n📆 Վաղվա այցերը — վաղվա ցուցակը\n🗓 Առաջիկա 7 օրը — շաբաթվա այցերը\n⏳ Սպասող հայտեր — դեռ չպատասխանված հայտերը՝ կրկին հաստատելու կամ մերժելու կոճակներով\n🧑 Ամրագրել որպես պացիենտ — տեսնել բոտը պացիենտի աչքերով\n\n"
               "💡 Մենյուն կորե՞լ է։ Ուղարկեք /start կամ սեղմեք 🏠։\n"
               "💡 Խորհուրդ՝ պատասխանեք հայտերին որքան հնարավոր է շուտ, որպեսզի ժամը չզբաղեցվի ուրիշի կողմից։")

PATIENT_GUIDE = ("📖 Ինչպես ամրագրել այց — 4 քայլ\n\n"
                 "1️⃣ Ընտրեք բժշկին\n«👨‍⚕️ Ընտրել բժիշկ» — եթե գիտեք՝ ում մոտ եք ուզում գնալ։\n«🩺 Ընտրել ըստ ծառայության» — եթե չգիտեք, բոտը կառաջարկի ճիշտ բժշկին։\nℹ️ կոճակով կարող եք կարդալ բժշկի մասին։\n\n"
                 "2️⃣ Ընտրեք այցի նպատակը\nՕրինակ՝ խորհրդատվություն կամ սուր ցավ։ Բոտը ինքը կհաշվի, թե որքան ժամանակ է պետք։\n\n"
                 "3️⃣ Ընտրեք ամիսը, օրը և ժամը\nՑույց են տրվում միայն ազատ ժամերը։\n\n"
                 "4️⃣ Գրեք Ձեր անունը և հեռախոսը\nՀայտը կուղարկվի բժշկին։ Երբ բժիշկը հաստատի, Դուք կստանաք հաղորդագրություն այստեղ, ինչպես նաև հիշեցում այցից առաջ (սեղմեք «✅ Կգամ»՝ հաստատելու համար) և կլինիկա հասնելու երթուղին։\n\n"
                 "📋 «Իմ ամրագրումները» — տեսնել, փոխել կամ չեղարկել Ձեր այցը։\n🔔 Ազատ ժամ չկա՞․ միացեք սպասման ցուցակին, և կտեղեկացնենք, երբ ժամ ազատվի։\n📞 «Կապ կլինիկայի հետ» — զանգ, Telegram, WhatsApp, Viber։\n\n"
                 "🔘 Օգտակար կոճակներ\n⬅️ Հետ — մեկ քայլ հետ\n🏠 Գլխավոր մենյու — սկսել սկզբից\n✖️ Ավարտել — փակել զրույցը\n\n"
                 "💡 Գրելու կարիք չկա․ պարզապես սեղմեք կոճակները։ Եթե բժիշկը չի կարող ընդունել ընտրված ժամին, Դուք կարող եք ընտրել այլ օր կամ ժամ։")

MENU_SERVICE_ACTION = {"general": "service_general", "pediatric": "service_pediatric", "orthodontics": "service_ortho"}


def norm_time(t: str) -> str:
    m = re.match(r"^(\d{1,2})[:.](\d{2})$", t or "") or re.match(r"^(\d{2})(\d{2})$", t or "")
    if not m:
        return ""
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return ""
    return f"{h:02d}:{mi:02d}"


def norm_phone(raw) -> str:
    """Accepts 091 123456, +374 91 123456, 37491123456, 0037491123456 or other international numbers."""
    x = re.sub(r"[\s\-().]", "", str(raw or ""))
    if x.startswith("00"):
        x = "+" + x[2:]
    if re.fullmatch(r"0\d{8}", x):
        x = "+374" + x[1:]
    elif re.fullmatch(r"\d{8}", x):
        x = "+374" + x
    elif re.fullmatch(r"\d{9,15}", x):
        x = "+" + x
    return x if re.fullmatch(r"\+\d{8,15}", x) else ""


NAME_RE = re.compile(r"^[^\W\d_][^\W\d_'’.\-]*(?:['’.\-][^\W\d_'’.\-]*)*(?: [^\W\d_][^\W\d_'’.\-]*(?:['’.\-][^\W\d_'’.\-]*)*)+$")


def valid_name(name: str) -> bool:
    if len(name) < 3 or len(name) > 60:
        return False
    # Letters plus ' ’ . - inside words, at least two words.
    return all(w and w[0].isalpha() and all(c.isalpha() or c in "'’.-" for c in w) for w in name.split(" ")) and len(name.split(" ")) >= 2


def route(p: dict, s: dict, clinic: Clinic, req: dict | None, now: int) -> dict:
    s = s or {}
    doctors = clinic.active_doctors()
    today = ymd(now)
    SERVICE = {k: v["name"] for k, v in clinic.specialties.items()}
    PRICE_NOTE = clinic.price_note
    TTL = float(clinic.booking["request_ttl_hours"]) * HOUR
    MAX_AHEAD = int(clinic.booking["max_days_ahead"])
    cur_month = int(today[5:7]) - 1
    next_month = (cur_month + 1) % 12

    out = {
        "action": "reply", "home_kb": False, "kind": p.get("kind"), "chat_id": p.get("chat_id"), "from_id": p.get("from_id"),
        "username": p.get("username") or "", "callback_id": p.get("callback_id") or "", "callback_text": "", "text": "",
        "first_name": p.get("first_name") or "",
        "old_request_id": s.get("request_id") or "__none__", "request_id": "__none__", "doctor_key": "", "doctor_name": "",
        "calendar_id": "", "filter_by_name": False, "approver_chat_id": "",
        "date": "", "date_next": "", "selected_time": "", "mode": "", "slot_start": "", "slot_end": "", "slot_key": "",
        "expires_at": "", "patient_chat_id": "", "patient_name": "", "full_name": s.get("full_name") or "",
        "saved_name": s.get("full_name") or "", "phone": "", "saved_phone": s.get("phone") or "", "service": "", "doctor_message": "",
        "replace_request_id": s.get("replace_request_id") or "", "replaces_request_id": "", "old_status": "",
        "calendar_event_id": "", "card_text": "", "reset_session": False, "menu_stage": "", "quick_rebook": s.get("quick_rebook") or "",
        "duration_min": 30, "visit_reason": s.get("visit_reason") or "", "visit_label": "", "reason_labels": [], "reason_text": "",
        "month_offset": -1, "staff_doctors": "[]", "staff_menu_text": "", "report": "", "rating": 0,
        "block_step": "", "block_labels": [], "wl_date": "",
    }

    def reply(t):
        out["action"] = "reply"; out["text"] = t
        return out

    def reply_home(t):
        out["action"] = "reply"; out["home_kb"] = True; out["text"] = t
        return out

    def reasons_for(d):
        return clinic.reasons_for(d)

    def reason_of(d, key):
        return next((x for x in reasons_for(d) if x["key"] == key), None)

    def svc_line(x):
        return "• " + x["label"] + " — " + str(x["min"]) + " րոպե · " + x["price"]

    def service_for(d):
        rs = reason_of(d, out["visit_reason"])
        if rs:
            return rs["name"]
        chosen = s.get("service") or ""
        fits = (chosen == SERVICE.get("general") and d["specialty"] == "general") or \
               (chosen == SERVICE.get("pediatric") and d["specialty"] == "pediatric") or \
               (chosen == SERVICE.get("orthodontics") and d["specialty"] == "orthodontics")
        return chosen if fits else SERVICE.get(d["specialty"], "")

    def doc_ctx(d):
        out["doctor_key"] = d["doctor_key"]; out["doctor_name"] = d["doctor_name"]; out["calendar_id"] = d.get("calendar_id") or ""
        out["approver_chat_id"] = str(d.get("approver_chat_id") or "")
        # Several doctors sharing one calendar -> events are told apart by the doctor's name in the title.
        out["filter_by_name"] = len([x for x in doctors if x.get("calendar_id") and x["calendar_id"] == d.get("calendar_id")]) > 1
        rs = reason_of(d, out["visit_reason"])
        out["duration_min"] = rs["min"] if rs else (clinic.duration_by_service(service_for(d)) or 30)
        out["visit_label"] = service_for(d)

    def ask_reason(d):
        out["visit_reason"] = ""; out["quick_rebook"] = ""; doc_ctx(d)
        rs = reasons_for(d)
        out["reason_labels"] = [x["label"] for x in rs]
        out["reason_text"] = ("Բժիշկ՝ " + d["doctor_name"] + "\nԽնդրում ենք ընտրել այցի նպատակը։ Դրանից կախված կհաշվարկենք այցի տևողությունը և կառաջարկենք համապատասխան ազատ ժամերը։\n\n"
                              + "\n".join(svc_line(x) for x in rs) + "\n\n" + PRICE_NOTE)
        out["action"] = "ask_reason"
        return out

    def set_date(dt):
        out["date"] = dt
        out["date_next"] = ymd(at(dt, "12:00") + DAY)

    def check_date(t):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", t or ""):
            return "Ընտրեք ամսաթիվը կոճակներից կամ գրեք ՏՏՏՏ-ԱԱ-ՕՕ ձևաչափով, օրինակ՝ 2026-10-12։"
        if not valid_date(t):
            return "Այդ ամսաթիվը գոյություն չունի։ Խնդրում ենք ընտրել վավեր ամսաթիվ։"
        if t < today:
            return "Ընտրեք այսօրվա կամ ապագա ամսաթիվ։"
        if t > ymd(now + MAX_AHEAD * DAY):
            return "Ամրագրումը հնարավոր է առավելագույնը 2 ամիս առաջ։ Ընտրեք ավելի մոտ ամսաթիվ։"
        if weekday(t) in (0, 6) and t not in clinic.extra_days:
            return "Կլինիկան աշխատում է երկուշաբթիից ուրբաթ։ Ընտրեք աշխատանքային օր։"
        return ""

    def build_request(d, hm, full_name, phone):
        set_date(s["appointment_date"]); out["selected_time"] = hm; out["mode"] = "time"; out["action"] = "check_availability"
        out["full_name"] = full_name; out["patient_name"] = full_name; out["phone"] = phone; out["service"] = service_for(d)
        out["replaces_request_id"] = s.get("replace_request_id") or ""
        out["slot_start"] = s["appointment_date"] + "T" + hm + ":00+04:00"
        start_ms = parse_ms(out["slot_start"])
        out["slot_end"] = s["appointment_date"] + "T" + hhmm(start_ms + out["duration_min"] * MIN) + ":00+04:00"
        out["slot_key"] = d["doctor_key"] + "|" + out["slot_start"]
        # Readable code: month+day - time - 3 random digits, e.g. 1015-1330-482
        out["request_id"] = s["appointment_date"][5:7] + s["appointment_date"][8:10] + "-" + hm.replace(":", "") + "-" + str(random.randint(100, 999))
        exp = min(now + TTL, start_ms)
        out["expires_at"] = iso_utc(int(exp))
        out["patient_chat_id"] = p.get("chat_id")
        who = full_name + (" (@" + p["username"] + ")" if p.get("username") else "")
        # A time change shows the old date/time (decoded from the old request code "MMDD-HHMM-xxx") instead of the code.
        om = re.match(r"^(\d{2})(\d{2})-(\d{2})(\d{2})-", out["replaces_request_id"] or "")
        old_when = (f"{int(today[:4]) + (1 if int(om.group(1)) < int(today[5:7]) else 0)}-{om.group(1)}-{om.group(2)}, {om.group(3)}:{om.group(4)}") if om else ""
        msg = ("🔁 Ժամի փոփոխության հայտ" + (("\nՆախկին ժամ՝ " + old_when + "\nՆոր ժամ՝ " + s["appointment_date"] + ", " + hm + "–" + out["slot_end"][11:16] + " (Երևան)") if old_when else "")) \
            if out["replaces_request_id"] else "🦷 Նոր ամրագրման հայտ"
        msg += "\nՀայտ՝ " + out["request_id"] + "\nՊացիենտ՝ " + who + "\nՀեռախոս՝ " + phone + "\nԾառայություն՝ " + out["service"] + "\nԲժիշկ՝ " + d["doctor_name"]
        if not old_when:
            msg += "\nԱմսաթիվ՝ " + s["appointment_date"] + "\nԺամ՝ " + hm + "–" + out["slot_end"][11:16] + " (Երևան)"
        if out["replaces_request_id"]:
            msg += "\n⚠️ Հաստատելու դեպքում նախկին ժամը (" + (old_when or "նախորդ ամրագրումը") + ") ինքնաբերաբար կչեղարկվի։"
        msg += "\nՀայտը վավեր է մինչև " + ymd(int(exp)) + " " + hhmm(int(exp)) + "։"
        out["doctor_message"] = msg
        return out

    def fill_from_request(r, d):
        out["visit_reason"] = next((x["key"] for x in clinic.reasons if x["name"] == r.get("service")), "")
        doc_ctx(d)
        out["request_id"] = r["request_id"]; out["patient_chat_id"] = str(r.get("chat_id"))
        out["patient_name"] = r.get("patient_full_name") or r.get("patient_name") or ""; out["full_name"] = out["patient_name"]
        out["phone"] = r.get("patient_phone") or ""; out["service"] = r.get("service") or ""; out["username"] = r.get("telegram_username") or ""
        out["slot_start"] = r["slot_start"]; out["slot_end"] = r["slot_end"]; out["slot_key"] = r.get("slot_key") or ""
        out["selected_time"] = str(r["slot_start"])[11:16]; set_date(str(r["slot_start"])[:10])
        a, b = parse_ms(r["slot_end"]), parse_ms(r["slot_start"])
        if a and b and a > b:
            out["duration_min"] = round((a - b) / MIN)
        out["old_status"] = r.get("status"); out["calendar_event_id"] = r.get("calendar_event_id") or ""
        out["replaces_request_id"] = r.get("replaces_request_id") or ""

    # ----- button taps under a message (doctor approval, patient booking card, rating, staff undo) -----
    if p.get("kind") == "callback":
        def deny(t):
            out["action"] = "deny_callback"; out["callback_text"] = t
            return out
        data = p.get("data") or ""
        m = re.match(r"^(ap|rj|cx|cy|nx|ch|ok|r[1-5]|ub)\|", data)
        # Staff undo of a blocked day/time: "ub|<doctor_key>|<calendar event id>".
        if m and m.group(1) == "ub":
            parts = data.split("|")
            bd = next((x for x in doctors if x["doctor_key"] == (parts[1] if len(parts) > 1 else "")), None)
            if not bd or len(parts) < 3 or not parts[2] or str(bd.get("approver_chat_id")) != p.get("from_id"):
                return deny("Այս գործողությունը հասանելի չէ։")
            doc_ctx(bd); out["calendar_event_id"] = parts[2]; out["card_text"] = (p.get("message_text") or "").split("\n\n")[0]
            out["action"] = "staff_unblock"; out["callback_text"] = "Փակումը չեղարկվում է…"
            return out
        if not m or not req:
            return deny("Հայտը չի գտնվել։")
        verb = m.group(1)
        d = next((x for x in doctors if x["doctor_key"] == req.get("doctor_key")), None)
        if not d:
            return deny("Բժիշկը չի գտնվել։")
        out["card_text"] = (p.get("message_text") or "").split("\n\n")[0]
        if verb in ("ap", "rj"):
            if not d.get("approver_chat_id") or str(d["approver_chat_id"]) != p.get("from_id"):
                return deny("Դուք իրավասու չեք մշակելու այս հայտը։")
            fill_from_request(req, d); out["mode"] = "approve"
            if req.get("status") != "pending":
                return deny("Այս հայտն արդեն մշակված է՝ " + STATUS_HY.get(req.get("status"), str(req.get("status"))) + "։")
            if verb == "rj":
                out["action"] = "reject"; out["callback_text"] = "Հայտը մերժվում է…"
                return out
            if not ((parse_ms(req.get("expires_at")) or 0) > now) or not ((parse_ms(req.get("slot_start")) or 0) > now):
                out["action"] = "expire"; out["callback_text"] = "Հայտի ժամկետը լրացել է։ Այցը չի ստեղծվել։"
                return out
            out["action"] = "approve"; out["callback_text"] = "Ստուգում եմ ժամը և ստեղծում այցը…"
            return out
        # Patient actions: only the person who made the booking may use them.
        if str(req.get("chat_id")) != p.get("from_id"):
            return deny("Այս ամրագրումը Ձերը չէ։")
        fill_from_request(req, d)

        def note(t):
            out["action"] = "patient_note"; out["text"] = t
            return out
        # Rating after the visit: "r1|<request>" … "r5|<request>".
        if re.fullmatch(r"r[1-5]", verb):
            if req.get("status") != "approved":
                return note("ℹ️ Այս այցը չի կայացել, ուստի գնահատել հնարավոր չէ։")
            if (req.get("rating") or 0) and int(req.get("rating")) > 0:
                return note("ℹ️ Դուք արդեն գնահատել եք այս այցը (" + str(req["rating"]) + "/5)։ Շնորհակալություն։")
            out["rating"] = int(verb[1]); out["action"] = "rate"; out["callback_text"] = "Շնորհակալություն գնահատականի համար"
            return out
        active = req.get("status") in ("approved", "pending") and (parse_ms(req.get("slot_start")) or 0) > now
        if not active:
            return note("ℹ️ Այս ամրագրումն այլևս ակտիվ չէ (" + STATUS_HY.get(req.get("status"), str(req.get("status"))) + ")։")
        if verb == "nx":
            return note("👍 Այցը մնում է ուժի մեջ։")
        if verb == "ok":
            if req.get("status") != "approved":
                return note("ℹ️ Այս հայտը դեռ սպասում է բժշկի հաստատմանը։")
            out["action"] = "patient_confirm"; out["callback_text"] = "Շնորհակալություն"
            out["text"] = "✅ Շնորհակալություն, Ձեր ներկայությունը հաստատված է։ Սպասում ենք Ձեզ։"
            return out
        if verb == "cx":
            out["action"] = "patient_cancel_ask"
            return out
        if verb == "cy":
            out["action"] = "patient_cancel"; out["callback_text"] = "Չեղարկում եմ…"; out["reset_session"] = s.get("request_id") == req["request_id"]
            return out
        if verb == "ch":
            out["quick_rebook"] = "yes"; out["action"] = "change_booking"; out["callback_text"] = "Ընտրեք նոր ամսաթիվ"; out["date"] = ""
            return out
        return deny("Անհայտ գործողություն։")

    # ----- ordinary message -----
    if not p.get("chat_id"):
        out["action"] = "ignore"
        return out
    t = p.get("text") or ""

    # ----- staff (approver) menu: dashboard, reports, blocking -----
    staff_docs = [d for d in doctors if d.get("approver_chat_id") and str(d["approver_chat_id"]) == str(p.get("chat_id"))]
    if staff_docs:
        out["staff_doctors"] = json.dumps([{"k": d["doctor_key"], "n": d["doctor_name"]} for d in staff_docs], ensure_ascii=False, separators=(",", ":"))
        out["staff_menu_text"] = ("👨‍⚕️ Բժշկի / ադմինիստրատորի մենյու\nՁեր բժիշկները՝ " + ", ".join(d["doctor_name"] for d in staff_docs)
                                  + "\n\nԸնտրեք բաժինը ստորև։\nԱռաջին անգա՞մ եք․ սեղմեք «" + S["guide"] + "»։\nՊացիենտի մենյուն փորձարկելու համար սեղմեք «"
                                  + S["patient"] + "»։ Այստեղ վերադառնալու համար ուղարկեք /start։")
        if re.match(r"^/(start|staff)(@\w+)?(\s|$)", t) or t in (S["staff"], L["home"], L["restart"]):
            out["action"] = "staff_menu"
            return out
        rep = {S["dash"]: "dash", S["today"]: "today", S["tomorrow"]: "tomorrow", S["week"]: "week", S["pending"]: "pending"}.get(t)
        if rep:
            out["action"] = "staff_report"; out["report"] = rep
            return out
        if t == S["patient"]:
            out["action"] = "welcome"
            return out
        if t == S["guide"] or re.match(r"^/help(@\w+)?$", t):
            return reply(STAFF_GUIDE)

        def ask_doc():
            out["action"] = "staff_block_ask"; out["block_step"] = "doctor"; out["menu_stage"] = "staff_block_doctor"
            out["block_labels"] = [d["doctor_name"] for d in staff_docs]
            out["text"] = "🚫 Ժամերի փակում\nՈ՞ր բժշկի համար եք փակում օրը կամ ժամը։"
            return out

        def ask_date(d):
            doc_ctx(d); out["action"] = "staff_block_ask"; out["block_step"] = "date"; out["menu_stage"] = "staff_block_date"
            labels, i = [], 0
            while len(labels) < 8 and i < 20:
                dd = ymd(now + i * DAY)
                w = weekday(dd)
                if w not in (0, 6):
                    labels.append(MON[int(dd[5:7]) - 1] + " " + str(int(dd[8:10])) + " " + SHORT_DAYS[w])
                i += 1
            out["block_labels"] = labels
            out["text"] = "🚫 Բժիշկ՝ " + d["doctor_name"] + "\nԸնտրեք օրը ստորև կամ գրեք ամսաթիվը, օրինակ՝ 25.10"
            return out

        def ask_time(d, dt):
            doc_ctx(d); set_date(dt); out["action"] = "staff_block_ask"; out["block_step"] = "time"; out["menu_stage"] = "staff_block_time"
            out["text"] = ("🚫 Բժիշկ՝ " + d["doctor_name"] + "\nՕր՝ " + dt + " (" + SHORT_DAYS[weekday(dt)]
                           + ")\n\nԸնտրեք՝ ամբողջ օրը կամ միջակայքը, կամ գրեք Ձեր ժամերը, օրինակ՝ 14:00-16:00")
            return out

        if t == S["block"]:
            return ask_date(staff_docs[0]) if len(staff_docs) == 1 else ask_doc()
        bst = str(s.get("stage") or "")
        if bst.startswith("staff_block_"):
            if t == L["back"]:
                out["action"] = "staff_menu"
                return out
            bdoc = next((d for d in staff_docs if d["doctor_key"] == s.get("doctor_key")), None)
            if bst == "staff_block_doctor":
                d = next((x for x in staff_docs if x["doctor_name"] == t), None)
                return ask_date(d) if d else reply("Խնդրում ենք ընտրել բժշկին կոճակներից։")
            if bst == "staff_block_date" and bdoc:
                dt = ""
                lm = re.match(r"^(\S+) (\d{1,2})(?: |$)", t)
                dm2 = re.match(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?$", t)
                iso = t if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t) else ""

                def mk(dd, mm, yy):
                    y = yy or (int(today[:4]) + (1 if mm < int(today[5:7]) else 0))
                    return f"{y}-{mm:02d}-{dd:02d}"
                if iso:
                    dt = iso
                elif dm2:
                    dt = mk(int(dm2.group(1)), int(dm2.group(2)), int(dm2.group(3)) if dm2.group(3) else 0)
                elif lm and lm.group(1) in MON:
                    dt = mk(int(lm.group(2)), MON.index(lm.group(1)) + 1, 0)
                if not dt or not valid_date(dt):
                    return reply("Չհասկացա ամսաթիվը։ Ընտրեք կոճակներից կամ գրեք, օրինակ՝ 25.10")
                if dt < today:
                    return reply("Այդ օրն արդեն անցել է։ Ընտրեք այսօրվա կամ ապագա օր։")
                if dt > ymd(now + 92 * DAY):
                    return reply("Կարելի է փակել առավելագույնը 3 ամիս առաջ։")
                return ask_time(bdoc, dt)
            if bst == "staff_block_time" and bdoc and s.get("appointment_date"):
                a = b = ""
                if t == S["whole"]:
                    a, b = "00:00", "23:59"
                else:
                    rm = re.search(r"(\d{1,2})(?:[:.](\d{2}))?\s*[-–—]\s*(\d{1,2})(?:[:.](\d{2}))?", t)
                    if rm:
                        a = norm_time(rm.group(1) + ":" + (rm.group(2) or "00"))
                        b = norm_time(rm.group(3) + ":" + (rm.group(4) or "00"))
                if not a or not b or b <= a:
                    return reply("Գրեք ժամային միջակայքը այսպես՝ 14:00-16:00, կամ ընտրեք կոճակներից։")
                dt = s["appointment_date"]
                if at(dt, b) <= now:
                    return reply("Այդ ժամն արդեն անցել է։ Ընտրեք ավելի ուշ ժամ։")
                doc_ctx(bdoc); set_date(dt)
                out["slot_start"] = dt + "T" + a + ":00+04:00"; out["slot_end"] = dt + "T" + b + ":00+04:00"; out["menu_stage"] = "idle"
                out["text"] = ("✅ Փակված է\nԲժիշկ՝ " + bdoc["doctor_name"] + "\nՕր՝ " + dt + "\nԺամ՝ " + ("ամբողջ օրը" if t == S["whole"] else a + "–" + b)
                               + "\n\nԱյս ժամերը պացիենտներին այլևս չեն առաջարկվի։ Արդեն ամրագրված այցերը ինքնաբերաբար չեն չեղարկվում։\nՍխալմամբ փակելու դեպքում սեղմեք ստորև։")
                out["staff_menu_text"] = "Ի՞նչ եք ցանկանում անել հետո։"
                out["action"] = "staff_block_create"
                return out

    if t == L["end"]:
        out["action"] = "end_chat"
        return out
    if t == L["noWait"]:
        return reply_home("Լավ, Ձեր հայտը մնում է ուժի մեջ։ Բժշկի պատասխանը կստանաք այստեղ։")
    if t == L["myBookings"]:
        out["action"] = "my_bookings"
        return out
    if t == L["contact"] or re.match(r"^/contact(@\w+)?$", t):
        out["action"] = "contact"
        return out
    if t == L["guide"] or re.match(r"^/help(@\w+)?$", t):
        return reply(PATIENT_GUIDE)

    # Doctor info buttons ("ℹ️ Արամի մասին") next to each doctor: show a short profile and keep the same buttons.
    if t.startswith("ℹ️ "):
        di = next((d for d in doctors if t in (d.get("info_label"), "ℹ️ " + d["doctor_name"].split(" ")[0])), None)
        if di:
            txt = "👨‍⚕️ " + di["doctor_name"] + "\n" + (di.get("bio") or SERVICE.get(di["specialty"], ""))
            txt += "\n\n🦷 Ծառայություններ և գներ՝\n" + "\n".join(svc_line(x) for x in reasons_for(di)) + "\n" + PRICE_NOTE
            if di.get("hours_text"):
                txt += "\n\n🕘 Ընդունելության ժամեր՝ " + di["hours_text"]
            txt += "\n\nԱմրագրելու համար սեղմեք «" + di["doctor_name"] + "» կոճակը։"
            return reply(txt)

    # Back: return exactly one step, based on where the patient is now.
    if t == L["back"]:
        st = s.get("stage") or ""
        bd = next((d for d in doctors if d["doctor_key"] == s.get("doctor_key")), None)
        if st == "awaiting_approval":
            out["action"] = "confirm_cancel"
            return out
        if st == "menu_service_doctors":
            out["action"] = "service_menu"; out["menu_stage"] = "menu_services"
            return out
        if bd and st == "awaiting_month":
            if s.get("replace_request_id"):
                out["action"] = "my_bookings"
                return out
            return ask_reason(bd)
        if bd and st == "awaiting_date":
            if s.get("replace_request_id"):
                out["action"] = "my_bookings"
                return out
            doc_ctx(bd); out["month_offset"] = -1; out["action"] = "doctor_chosen"
            return out
        if bd and st == "awaiting_reason":
            spec = next((k for k, v in SERVICE.items() if v == (s.get("service") or "") and k in MENU_SERVICE_ACTION), None)
            out["action"] = MENU_SERVICE_ACTION[spec] if spec else "doctor_menu"
            out["service"] = s.get("service") if spec else ""
            out["menu_stage"] = "menu_service_doctors" if spec else "menu_doctors"
            return out
        if bd and st == "awaiting_time":
            doc_ctx(bd)
            out["month_offset"] = 1 if s.get("appointment_date") and s["appointment_date"][:7] != today[:7] else 0
            out["action"] = "doctor_chosen"
            return out
        if bd and st == "awaiting_name" and s.get("appointment_date"):
            doc_ctx(bd); set_date(s["appointment_date"]); out["mode"] = "date"; out["action"] = "check_availability"
            return out
        if bd and st == "awaiting_phone" and s.get("selected_time") and s.get("appointment_date"):
            doc_ctx(bd); set_date(s["appointment_date"]); out["selected_time"] = s["selected_time"]; out["action"] = "ask_name"
            return out
        out["action"] = "welcome"
        return out

    # After a rejection / taken slot / expiry: try again with the same doctor.
    if t in (L["otherDay"], L["otherTime"]):
        if s.get("stage") == "awaiting_approval":
            out["action"] = "confirm_cancel"
            return out
        od = next((d for d in doctors if d["doctor_key"] == s.get("doctor_key")), None)
        if not od or not od.get("calendar_id"):
            out["action"] = "welcome"
            return out
        doc_ctx(od); out["quick_rebook"] = "yes"
        if t == L["otherTime"] and s.get("appointment_date") and not check_date(s["appointment_date"]):
            set_date(s["appointment_date"]); out["mode"] = "date"; out["action"] = "check_availability"
            return out
        out["action"] = "doctor_chosen"
        return out

    # Waitlist: offered when there is no free date / time. Notified when a booking with this doctor is cancelled.
    if t == L["waitlist"]:
        wd = next((d for d in doctors if d["doctor_key"] == s.get("doctor_key")), None)
        if not wd or s.get("stage") not in ("awaiting_month", "awaiting_date", "awaiting_time"):
            return reply_home("Սպասման ցուցակին կարելի է միանալ բժիշկ և օր ընտրելիս, երբ ազատ ժամ չկա։")
        doc_ctx(wd)
        out["wl_date"] = s["appointment_date"] if s.get("stage") == "awaiting_time" and s.get("appointment_date") else ""
        out["patient_name"] = s.get("full_name") or p.get("first_name") or ""
        out["action"] = "waitlist_join"; out["home_kb"] = True
        out["text"] = ("🔔 Դուք ավելացվեցիք սպասման ցուցակում\nԲժիշկ՝ " + wd["doctor_name"] + "\nՕր՝ " + (out["wl_date"] or "ցանկացած")
                       + "\n\nԵրբ այս բժշկի մոտ ժամ ազատվի, անմիջապես կտեղեկացնենք այստեղ։ Ժամը կստանա առաջինը ամրագրողը։")
        return out

    # Main menu while a request is still waiting: ask before cancelling it.
    if t in (L["home"], L["restart"]) and s.get("stage") == "awaiting_approval":
        out["action"] = "confirm_cancel"
        return out
    if re.match(r"^/start(@\w+)?(\s|$)", t) or t in (L["restart"], L["home"], L["yesCancel"]):
        out["action"] = "welcome"
        return out
    if re.match(r"^/myid(@\w+)?$", t):
        return reply_home("Ձեր Telegram chat ID-ն՝ " + str(p.get("chat_id")))

    # Phone step (a shared contact arrives without text, so this comes before the text check).
    if s.get("stage") == "awaiting_phone":
        nd = next((d for d in doctors if d["doctor_key"] == s.get("doctor_key")), None)
        if not nd or not s.get("selected_time") or not s.get("appointment_date") or not s.get("full_name"):
            return reply_home(RESTART_MSG)
        doc_ctx(nd)
        if t == L["otherDate"]:
            out["action"] = "doctor_chosen"
            return out
        if p.get("contact_phone") and p.get("contact_user_id") and p["contact_user_id"] != p.get("from_id"):
            return reply("Խնդրում ենք կիսվել Ձեր սեփական համարով կամ գրել այն, օրինակ՝ +374 91 123456։")
        phone = norm_phone(p.get("contact_phone") or t)
        if not phone:
            return reply("Խնդրում ենք գրել ճիշտ հեռախոսահամար, օրինակ՝ +374 91 123456 կամ 091 123456, կամ սեղմել «📱 Կիսվել իմ համարով»։")
        if not out["approver_chat_id"]:
            return reply_home(NO_APPROVER)
        return build_request(nd, s["selected_time"], s["full_name"], phone)
    if not t:
        return reply_home("Ես հասկանում եմ միայն տեքստային հաղորդագրություններ և կոճակներ։")

    # Name step first, so a typed name is never mistaken for a menu button.
    if s.get("stage") == "awaiting_name":
        nd = next((d for d in doctors if d["doctor_key"] == s.get("doctor_key")), None)
        if not nd or not s.get("selected_time") or not s.get("appointment_date"):
            return reply_home(RESTART_MSG)
        doc_ctx(nd)
        if t == L["otherDate"]:
            out["action"] = "doctor_chosen"
            return out
        name = re.sub(r"\s+", " ", t).strip()
        if not valid_name(name):
            return reply("Խնդրում ենք գրել անունը և ազգանունը տառերով, օրինակ՝ Անի Պետրոսյան։")
        if not out["approver_chat_id"]:
            return reply_home(NO_APPROVER)
        # Next: ask for a phone number.
        out["action"] = "ask_phone"; out["full_name"] = name; out["selected_time"] = s["selected_time"]; set_date(s["appointment_date"])
        return out

    menu = {L["chooseDoctor"]: "doctor_menu", L["help"]: "service_menu"}
    for spec in clinic.service_menu:
        if spec in MENU_SERVICE_ACTION:
            menu[SERVICE[spec]] = MENU_SERVICE_ACTION[spec]
    menu_service = {"doctor_menu": "", "service_general": SERVICE.get("general", ""), "service_pediatric": SERVICE.get("pediatric", ""),
                    "service_ortho": SERVICE.get("orthodontics", "")}
    menu_stage = {"doctor_menu": "menu_doctors", "service_menu": "menu_services", "service_general": "menu_service_doctors",
                  "service_pediatric": "menu_service_doctors", "service_ortho": "menu_service_doctors"}
    picked = next((d for d in doctors if d["doctor_name"] == t), None)
    if (t in menu or picked) and s.get("stage") == "awaiting_approval":
        out["action"] = "confirm_cancel"
        return out
    if t in menu:
        out["action"] = menu[t]; out["menu_stage"] = menu_stage.get(out["action"], "")
        if out["action"] in menu_service:
            out["service"] = menu_service[out["action"]]
        return out
    if picked:
        doc_ctx(picked); out["quick_rebook"] = ""
        if not picked.get("calendar_id"):
            return reply("Այս բժշկի ժամանակացույցը դեռ միացված չէ։ Ընտրեք մեկ այլ բժշկի։")
        return ask_reason(picked)

    # Visit reason chosen -> work out the length and show the free dates.
    if s.get("stage") == "awaiting_reason":
        rd = next((d for d in doctors if d["doctor_key"] == s.get("doctor_key")), None)
        if not rd:
            return reply_home(RESTART_MSG)
        rs = next((x for x in reasons_for(rd) if x["label"] == t), None)
        if not rs:
            return reply("Խնդրում ենք ընտրել այցի նպատակը ստորև նշված կոճակներից։")
        out["visit_reason"] = rs["key"]; doc_ctx(rd); out["action"] = "doctor_chosen"
        return out

    sdoc = next((d for d in doctors if d["doctor_key"] == s.get("doctor_key")), None)
    if s.get("stage") in ("awaiting_month", "awaiting_date", "awaiting_time"):
        if not sdoc:
            return reply_home(RESTART_MSG)
        doc_ctx(sdoc)
        if t == L["otherDate"]:
            out["action"] = "doctor_chosen"
            return out
        # Month buttons ("📅 Հոկտեմբեր 2026") and the month switch on the date screen.
        if "📅" in t:
            if MONTHS[cur_month] in t:
                out["month_offset"] = 0; out["action"] = "doctor_chosen"
                return out
            if MONTHS[next_month] in t:
                out["month_offset"] = 1; out["action"] = "doctor_chosen"
                return out
        if s.get("stage") == "awaiting_month":
            return reply("Խնդրում ենք ընտրել ամիսը ստորև նշված կոճակներից։")
        dm = re.match(r"^(\d{4}-\d{1,2}-\d{1,2})", t)
        # Date buttons look like "հոկ 14 Չրք"; the year is this year, or next year for an earlier month.
        db = re.search(r"(\d{1,2})\.(\d{1,2})$", t)
        dbv = (int(db.group(1)), int(db.group(2))) if db else None
        if not dbv:
            x = re.match(r"^(\S+) (\d{1,2})(?: |$)", t)
            if x and x.group(1) in MON:
                dbv = (int(x.group(2)), MON.index(x.group(1)) + 1)
        btn_date = ""
        if dbv:
            dd, mm = dbv
            y = int(today[:4]) + (1 if mm < int(today[5:7]) else 0)
            btn_date = f"{y}-{mm:02d}-{dd:02d}"
        if s.get("stage") == "awaiting_date" or dm or btn_date:
            dt = dm.group(1) if dm else (btn_date or t)
            err = check_date(dt)
            if err:
                return reply(err)
            set_date(dt); out["mode"] = "date"; out["action"] = "check_availability"
            return out
        try:
            opts = json.loads(s.get("slot_options") or "[]")
        except ValueError:
            opts = []
        hm = norm_time(t)
        if not hm or hm not in opts:
            return reply("Խնդրում ենք ընտրել ազատ ժամերից մեկը կոճակներից։\nԱզատ ժամեր՝ " + (", ".join(opts) or "—"))
        if not out["approver_chat_id"]:
            return reply_home(NO_APPROVER)
        # Trying again after a rejection, or changing a booking: reuse the saved name and phone.
        saved_phone = norm_phone(s.get("phone"))
        if s.get("quick_rebook") == "yes" and s.get("full_name") and saved_phone:
            return build_request(sdoc, hm, s["full_name"], saved_phone)
        # Ask who the visit is for before sending the request.
        out["action"] = "ask_name"; out["selected_time"] = hm; set_date(s["appointment_date"])
        return out

    if s.get("stage") == "awaiting_approval":
        return reply_home("Ձեր հայտը սպասում է բժշկի հաստատմանը։ Պատասխանը կստանաք այստեղ։")
    if staff_docs:
        out["action"] = "staff_menu"
        return out
    return reply_home("Չհասկացա։ Սկսելու համար սեղմեք " + HOME + "։")
