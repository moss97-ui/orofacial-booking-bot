"""Parity tests: the Python port must make the same decisions as the original n8n JavaScript.

Hundreds of generated situations are run through both the n8n Code-node JavaScript (tests/parity/js, via Node.js)
and the Python modules, and the results are compared field by field.
Skipped automatically when Node.js is not installed.
"""
from __future__ import annotations

import itertools
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bot.clinic import load_clinic
from bot.reports import build_staff_report
from bot.router import route
from bot.slots import compute_available_dates, compute_free_slots
from bot.timeutil import DAY, HOUR, MIN, at, iso_utc

HERE = Path(__file__).parent
CLINIC = load_clinic(HERE / "clinic_test.yaml")
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")

DOCS_JS = [{"doctor_key": d["doctor_key"], "doctor_name": d["doctor_name"], "specialty": d["specialty"],
            "calendar_id": d["calendar_id"], "approver_chat_id": d["approver_chat_id"], "active": True} for d in CLINIC.doctors]
NOW_MON = at("2026-10-12", "10:00")
NOW_SAT = at("2026-10-10", "08:30")


def run_js(scenarios):
    res = subprocess.run(["node", str(HERE / "parity" / "runner.js")], input=json.dumps(scenarios), capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def mask(v):
    if isinstance(v, str):
        return re.sub(r"(\d{4}-\d{4})-\d{3}", r"\1-XXX", v)
    if isinstance(v, list):
        return [mask(x) for x in v if x != "·"]
    return v


# ----------------------------------------------------------------------------- router
STAGES = [
    {},
    {"stage": "idle"},
    {"stage": "menu_doctors"},
    {"stage": "menu_service_doctors", "service": "Ընդհանուր խորհրդատվություն"},
    {"stage": "awaiting_reason", "doctor_key": "aram"},
    {"stage": "awaiting_reason", "doctor_key": "narek", "service": "Օրթոդոնտիա"},
    {"stage": "awaiting_month", "doctor_key": "davit", "visit_reason": "surgery"},
    {"stage": "awaiting_month", "doctor_key": "aram", "replace_request_id": "1104-0900-975"},
    {"stage": "awaiting_date", "doctor_key": "ani", "visit_reason": "clean"},
    {"stage": "awaiting_time", "doctor_key": "aram", "appointment_date": "2026-10-14", "slot_options": '["09:00","09:30","10:00"]', "visit_reason": "pain"},
    {"stage": "awaiting_time", "doctor_key": "aram", "appointment_date": "2026-11-04", "slot_options": '["09:00"]', "quick_rebook": "yes",
     "full_name": "Samson Israyelyan", "phone": "+37499112233", "replace_request_id": "1104-0900-975", "visit_reason": "pain"},
    {"stage": "awaiting_name", "doctor_key": "mariam", "appointment_date": "2026-10-15", "selected_time": "11:00", "full_name": "Անի Պետրոսյան"},
    {"stage": "awaiting_phone", "doctor_key": "lilit", "appointment_date": "2026-10-15", "selected_time": "11:00", "full_name": "Անի Պետրոսյան", "phone": "+37491123456"},
    {"stage": "awaiting_approval", "doctor_key": "aram", "request_id": "1014-0900-111"},
    {"stage": "staff_block_doctor"},
    {"stage": "staff_block_date", "doctor_key": "ani"},
    {"stage": "staff_block_time", "doctor_key": "ani", "appointment_date": "2026-10-14"},
]
TEXTS = ["/start", "/help", "/myid", "/contact", "", "hello", "🏠 Գլխավոր մենյու", "✖️ Ավարտել", "Ոչ, սպասել", "Այո, չեղարկել հայտը",
         "📋 Իմ ամրագրումները", "📞 Կապ կլինիկայի հետ", "❓ Ինչպես օգտվել", "👨‍⚕️ Ընտրել բժիշկ", "🩺 Ընտրել ըստ ծառայության",
         "Ընդհանուր խորհրդատվություն", "Մանկական ստոմատոլոգիա", "Օրթոդոնտիա", "Արամ Սարգսյան", "Դավիթ Գրիգորյան", "Նարեկ Հովհաննիսյան",
         ("ℹ️ Արամի մասին", "ℹ️ Արամ"), ("ℹ️ Դավթի մասին", "ℹ️ Դավիթ"), "🩺 Խորհրդատվություն", "⚡ Սուր ցավ", "🦷 Ատամի բուժում",
         "😁 Օրթոդոնտիկ բուժում", "🔧 Հեռացում / վիրահատություն", "⬅️ Հետ", "📅 Այլ օր", "🕐 Այլ ժամ", "🔔 Սպասման ցուցակ", "Այլ ամսաթիվ",
         "📅 Հոկտեմբեր 2026", "📅 Նոյեմբեր 2026", "📅 Նոյեմբեր →", "← 📅 Հոկտեմբեր", "հոկ 14 Չրք", "հոկ 18 Կիր", "նոյ 4 Չրք", "դեկ 20 Կիր",
         "2026-10-14", "2026-10-10", "2026-10-11", "2026-02-30", "2027-01-20", "09:00", "9.30", "10:00", "12:00",
         "Անի Պետրոսյան", "Samson Israyelyan", "Ani", "Անի 2", "091 123456", "+374 91 123456", "12345",
         "📊 Վահանակ", "⏳ Սպասող հայտեր", "📅 Այսօրվա այցերը", "🗓 Առաջիկա 7 օրը", "🧑 Ամրագրել որպես պացիենտ", "❓ Ուղեցույց",
         "🚫 Փակել օր / ժամ", "Անի Մկրտչյան", "25.10", "01.10", "🚫 Ամբողջ օրը", "🌇 13:00–18:00", "14:00 - 15:30", "9-11", "16:00-15:00"]


def router_cases():
    for (stage, text, chat, now) in itertools.product(STAGES, TEXTS, ["1", "9"], [NOW_MON, NOW_SAT]):
        py_text, js_text = (text if isinstance(text, tuple) else (text, text))
        p = {"kind": "message", "chat_id": chat, "from_id": chat, "username": "patient", "callback_id": "", "data": "", "first_name": "Գոռ",
             "lookup_request_id": "__none__", "message_id": 0, "message_text": "", "contact_phone": "", "contact_user_id": ""}
        s = dict(stage, chat_id=chat) if stage else {}
        yield p | {"text": py_text}, p | {"text": js_text}, s, None, now
    # contact shared at the phone step
    s = dict(STAGES[12], chat_id="1")
    for cphone, cuser in [("37491123456", "1"), ("37491123456", "7")]:
        p = {"kind": "message", "chat_id": "1", "from_id": "1", "username": "", "callback_id": "", "data": "", "text": "", "first_name": "Գոռ",
             "lookup_request_id": "__none__", "message_id": 0, "message_text": "", "contact_phone": cphone, "contact_user_id": cuser}
        yield p, p, s, None, NOW_MON


def request_row(status, start="2026-10-14T09:00:00+04:00", end="2026-10-14T09:30:00+04:00", chat="1", doctor="aram", **kw):
    return {"id": 5, "request_id": "1014-0900-111", "chat_id": chat, "doctor_key": doctor, "status": status, "slot_start": start, "slot_end": end,
            "slot_key": doctor + "|" + start, "expires_at": iso_utc(NOW_MON + HOUR), "service": "Սուր ցավ (շտապ այց)", "patient_full_name": "Գոռ Պետրոսյան",
            "patient_phone": "+37499112233", "telegram_username": "gor", "calendar_event_id": "evt1" if status == "approved" else "",
            "replaces_request_id": "", "rating": 0, **kw}


def callback_cases():
    reqs = [request_row("pending"), request_row("approved"), request_row("rejected"), request_row("cancelled"),
            request_row("pending", expires_at=iso_utc(NOW_MON - MIN)), request_row("approved", rating=4),
            request_row("approved", start="2026-10-12T08:00:00+04:00", end="2026-10-12T08:30:00+04:00"),
            request_row("pending", replaces_request_id="1104-0900-975"), request_row("approved", doctor="davit", start="2026-10-14T11:00:00+04:00", end="2026-10-14T12:30:00+04:00")]
    verbs = ["ap", "rj", "cx", "cy", "nx", "ch", "ok", "r1", "r4", "r5", "zz"]
    for req, verb, who in itertools.product(reqs, verbs, ["1", "9", "7"]):
        p = {"kind": "callback", "chat_id": who, "from_id": who, "username": "", "callback_id": "q1", "data": verb + "|" + req["request_id"], "text": "",
             "first_name": "", "lookup_request_id": req["request_id"], "message_id": 77, "message_text": "Card line 1\nline 2\n\nfooter",
             "contact_phone": "", "contact_user_id": ""}
        for s in ({}, {"chat_id": who, "request_id": req["request_id"]}):
            yield p, p, s, req, NOW_MON
    for data, who in [("ub|ani|abc123", "9"), ("ub|ani|abc123", "1"), ("ub|nobody|x", "9"), ("ub|ani|", "9"), ("ap|missing", "9")]:
        p = {"kind": "callback", "chat_id": who, "from_id": who, "username": "", "callback_id": "q1", "data": data, "text": "", "first_name": "",
             "lookup_request_id": "__none__", "message_id": 77, "message_text": "✅ Փակված է\nԲժիշկ\n\nfoot", "contact_phone": "", "contact_user_id": ""}
        yield p, p, {}, None, NOW_MON


def test_router_matches_n8n():
    cases = list(router_cases()) + list(callback_cases())
    scenarios = [{"kind": "route", "now": now, "nodes": {"Parse update": [pj], "Load patient session": [s] if s else [],
                  "Load doctors": DOCS_JS, "Load booking request": [req] if req else []}} for (_, pj, s, req, now) in cases]
    js = run_js(scenarios)
    assert len(js) == len(cases)
    mismatches = []
    for (pp, pj, s, req, now), j in zip(cases, js):
        py = route(pp, s, CLINIC, req, now)
        if j is None:
            assert py["action"] == "ignore"
            continue
        if "error" in j:
            # Known n8n bug: staff typing an impossible date such as "9.30" crashed the n8n Code node (no reply).
            # The Python version answers with a friendly "didn't understand the date" message instead.
            assert py["action"] == "reply" and "Չհասկացա" in py["text"], (pp, j)
            continue
        for k, v in j.items():
            if mask(py.get(k)) != mask(v):
                mismatches.append((pp.get("text") or pp.get("data"), s.get("stage"), k, mask(v), mask(py.get(k))))
    assert not mismatches, f"{len(mismatches)} mismatches, first: {mismatches[:5]}"
    assert len(cases) > 2000


# ----------------------------------------------------------------------------- slots and dates
def ev(eid, summary, start, end, **kw):
    return {"id": eid, "status": "confirmed", "summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end}, **kw}


EVENT_SETS = [
    [],
    [ev("e1", "Արամ Սարգսյան — visit", "2026-10-14T10:00:00+04:00", "2026-10-14T11:00:00+04:00"),
     ev("e2", "Անի Մկրտչյան — visit", "2026-10-14T12:00:00+04:00", "2026-10-14T13:00:00+04:00"),
     ev("e3", "⛔ Փակ — Արամ Սարգսյան", "2026-10-14T13:30:00+04:00", "2026-10-14T14:00:00+04:00"),
     ev("e4", "Արամ Սարգսյան cancelled", "2026-10-14T09:00:00+04:00", "2026-10-14T09:30:00+04:00", status="cancelled"),
     ev("e5", "Արամ Սարգսյան free", "2026-10-14T09:30:00+04:00", "2026-10-14T10:00:00+04:00", transparency="transparent"),
     {"id": "e6", "summary": "Արամ Սարգսյան vacation", "start": {"date": "2026-10-16"}, "end": {"date": "2026-10-17"}}],
    [ev("bad", "Արամ Սարգսյան", "nonsense", "2026-10-14T11:00:00+04:00")],
]
HOLD_SETS = [
    [],
    [request_row("pending", start="2026-10-14T11:00:00+04:00", end="2026-10-14T12:00:00+04:00", chat="2") | {"request_id": "a1"},
     request_row("approved", start="2026-10-15T09:00:00+04:00", end="2026-10-15T10:30:00+04:00", chat="2") | {"request_id": "a2"},
     request_row("rejected", start="2026-10-14T14:00:00+04:00", end="2026-10-14T14:30:00+04:00", chat="1") | {"request_id": "a3"},
     request_row("pending", start="2026-10-14T09:00:00+04:00", end="2026-10-14T09:30:00+04:00", chat="2", expires_at=iso_utc(NOW_MON - MIN)) | {"request_id": "a4"}],
]


def slot_inputs():
    base = {"chat_id": "1", "doctor_name": "Արամ Սարգսյան", "filter_by_name": True, "visit_label": "Սուր ցավ (շտապ այց)", "request_id": "a1"}
    for day, doc, dur, mode, sel, now in itertools.product(["2026-10-14", "2026-10-16", "2026-10-17", "2026-10-10", "2026-10-12"], ["aram", "narek"],
                                                           [30, 60, 90], ["date", "time", "approve"], ["09:00", "11:00", "14:30"], [NOW_MON, NOW_SAT]):
        name = next(d["doctor_name"] for d in CLINIC.doctors if d["doctor_key"] == doc)
        yield base | {"date": day, "doctor_key": doc, "doctor_name": name, "duration_min": dur, "mode": mode, "selected_time": sel}, now


def test_free_slots_match_n8n():
    cases = [(r, e, h, now) for (r, now) in slot_inputs() for e in EVENT_SETS for h in HOLD_SETS]
    js = run_js([{"kind": "free", "now": now, "nodes": {"Route": [r], "Read day events": e, "Load slot holds": h}} for (r, e, h, now) in cases])
    bad = []
    for (r, e, h, now), j in zip(cases, js):
        py = compute_free_slots(r, e, h, CLINIC, now)
        for k in ("ok", "free", "has_free", "free_json", "next_stage", "reply", "problem"):
            if py[k] != j[k]:
                bad.append((r["date"], r["doctor_key"], r["mode"], k, j[k], py[k]))
    assert not bad, bad[:5]


def test_available_dates_match_n8n():
    cases = []
    for (r, now) in slot_inputs():
        if r["mode"] != "date" or r["selected_time"] != "09:00" or r["date"] != "2026-10-14":
            continue
        for mo in (-1, 0, 1):
            for e in EVENT_SETS:
                for h in HOLD_SETS:
                    cases.append((r | {"month_offset": mo}, e, h, now))
    js = run_js([{"kind": "dates", "now": now, "nodes": {"Route": [r], "Read upcoming events": e, "Load doctor holds": h}} for (r, e, h, now) in cases])
    bad = []
    for (r, e, h, now), j in zip(cases, js):
        py = compute_available_dates(r, e, h, CLINIC, now)
        for k in ("pick_month", "reply", "month_labels", "has_dates", "labels", "toggle"):
            if mask(py.get(k)) != mask(j.get(k)):
                bad.append((r["doctor_key"], r["month_offset"], k, j.get(k), py.get(k)))
    assert not bad, bad[:5]


def test_staff_report_matches_n8n():
    rows = [request_row(st, start=f"2026-10-{d}T{t}:00+04:00", end=f"2026-10-{d}T{t[:3]}30:00+04:00", doctor=doc, rating=rt,
                        patient_confirmed="2026-10-12 09:00" if conf else "") | {"request_id": f"r{i}", "createdAt": iso_utc(NOW_MON - DAY), "updatedAt": iso_utc(NOW_MON - DAY)}
            for i, (st, d, t, doc, rt, conf) in enumerate([("approved", "12", "11:00", "aram", 0, True), ("approved", "12", "09:00", "ani", 5, False),
                                                           ("approved", "13", "10:00", "davit", 2, False), ("pending", "14", "09:00", "aram", 0, False),
                                                           ("cancelled", "15", "09:00", "aram", 0, False), ("rejected", "15", "10:00", "ani", 0, False),
                                                           ("approved", "18", "10:00", "narek", 0, False), ("approved", "25", "10:00", "aram", 0, False)])]
    staff = json.dumps([{"k": d["doctor_key"], "n": d["doctor_name"]} for d in CLINIC.doctors], ensure_ascii=False)
    reps = ["dash", "today", "tomorrow", "week", "pending"]
    js = run_js([{"kind": "report", "now": NOW_MON, "nodes": {"Route": [{"staff_doctors": staff, "report": rp}], "Load all bookings": rows}} for rp in reps])
    for rp, j in zip(reps, js):
        py = build_staff_report({"staff_doctors": staff, "report": rp}, rows, NOW_MON)
        assert py["text"] == j["text"], rp
        assert [c["text"] for c in py["cards"]] == [c["text"] for c in j["cards"]], rp
