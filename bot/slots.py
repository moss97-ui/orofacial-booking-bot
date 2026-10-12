"""Free time slots and available dates.

Free start times for a visit of the chosen length (30/60/90 min) = the doctor's shift inside
clinic hours, weekdays only (plus optional extra days), minus calendar events (visits, breaks,
"⛔ Փակ" blocks), minus active booking requests, minus past times.
"""
from __future__ import annotations

import json

from .clinic import Clinic
from .texts import DAYS, MON, MONTHS, SHORT_DAYS
from .timeutil import DAY, MIN, OFFSET, at, hhmm, parse_ms, weekday, ymd


def active_events(events: list) -> list:
    return [e for e in events if e and e.get("id") and e.get("status") != "cancelled" and e.get("transparency") != "transparent"]


def event_blocks(events: list, filter_by_name: bool, doctor_name: str):
    """Busy intervals [start, end) from calendar events; bad=True if an event has unreadable times."""
    mine = [e for e in events if not filter_by_name or doctor_name in str(e.get("summary") or "")]
    blocks, bad = [], False
    for e in mine:
        st, en = e.get("start") or {}, e.get("end") or {}
        if st.get("date"):
            b = (parse_ms(st["date"] + "T00:00:00" + OFFSET), parse_ms((en.get("date") or st["date"]) + "T00:00:00" + OFFSET))
        else:
            b = (parse_ms(st.get("dateTime")), parse_ms(en.get("dateTime")))
        if b[0] is None or b[1] is None:
            bad = True
        blocks.append(b)
    return blocks, bad


def held_intervals(holds: list, now: int, step: int, chat_id, exclude_request_id=None, include_rejected=True) -> list:
    held = []
    for x in holds:
        if not x or not x.get("request_id") or x["request_id"] == exclude_request_id:
            continue
        st = x.get("status")
        if st in ("approving", "approved") or (st == "pending" and (parse_ms(x.get("expires_at")) or 0) > now):
            a = parse_ms(x.get("slot_start"))
            held.append((a, parse_ms(x.get("slot_end")) or a + step))
    # Times the doctor already rejected for this patient are not offered to them again.
    if include_rejected:
        for x in holds:
            if x and x.get("status") == "rejected" and str(x.get("chat_id")) == str(chat_id):
                a = parse_ms(x.get("slot_start"))
                held.append((a, a + 1))
    return held


def _overlaps(intervals, t, dur):
    return any(b[0] is not None and b[1] is not None and t < b[1] and t + dur > b[0] for b in intervals)


def _day_window(clinic: Clinic, doctor_key: str, day: str):
    """(start_ms, end_ms) of the doctor's working window that day, or None."""
    sh = clinic.shift(doctor_key)
    extra = (clinic.extra_days.get(day) or {}).get(doctor_key)
    if not sh:
        return None, "no_shift"
    dow = weekday(day)
    wk = sh.get("saturday") if dow == 6 else sh.get("sunday") if dow == 0 else None
    if dow in (0, 6) and not extra and not wk:
        return None, "weekend"
    if extra:
        return (at(day, extra[0]), at(day, extra[1])), ""
    if wk:
        return (max(at(day, wk[0]), at(day, clinic.info["open"])), min(at(day, wk[1]), at(day, clinic.info["close"]))), ""
    end_hm = sh.get("friday_end") if dow == 5 and sh.get("friday_end") else sh["end"]
    return (max(at(day, sh["start"]), at(day, clinic.info["open"])), min(at(day, end_hm), at(day, clinic.info["close"]))), ""


def compute_free_slots(r: dict, events: list, holds: list, clinic: Clinic, now: int) -> dict:
    step = int(clinic.booking["step_minutes"]) * MIN
    dur = (int(r.get("duration_min") or 30)) * MIN
    lead = int(clinic.booking["lead_minutes"]) * MIN
    events = active_events(events)
    holds = [x for x in holds if x and x.get("request_id")]
    dow = weekday(r["date"])
    free, problem = [], ""
    window, problem = _day_window(clinic, r["doctor_key"], r["date"])
    if window:
        blocks, bad = event_blocks(events, r.get("filter_by_name"), r["doctor_name"])
        if bad:
            problem = "bad_event"
        held = held_intervals(holds, now, step, r.get("chat_id"), exclude_request_id=r.get("request_id"),
                              include_rejected=r.get("mode") != "approve")
        if not problem:
            t = window[0]
            while t + dur <= window[1]:
                if t >= now + lead and not _overlaps(blocks, t, dur) and not _overlaps(held, t, dur):
                    free.append(hhmm(t))
                t += step
    ok = len(free) > 0 if r.get("mode") == "date" else r.get("selected_time") in free
    day_label = f"{r['date']} ({DAYS[dow]})"
    if problem == "bad_event":
        reply = "Ներողություն, օրացույցում սխալ գրառում կա, և չեմ կարող ստուգել ազատ ժամերը։ Փորձեք այլ ամսաթիվ կամ ավելի ուշ։"
    elif free:
        reply = (("Ցավոք, " + r["selected_time"] + "-ն այլևս ազատ չէ։\n\n") if r.get("mode") == "time" else "") + \
            "Բժիշկ՝ " + r["doctor_name"] + "\nԱմսաթիվ՝ " + day_label + "\nԱյց՝ " + (r.get("visit_label") or "—") + \
            "\nՏևողությունը՝ " + str(int(r.get("duration_min") or 30)) + " րոպե։\nԸնտրեք այցի սկզբի ժամը ստորև նշված կոճակներից։"
    else:
        reply = "Ցավոք, " + day_label + "-ին " + r["doctor_name"] + "-ի մոտ ազատ ժամ չկա։\nՍեղմեք «Այլ ամսաթիվ»։"
    return {"mode": r.get("mode"), "ok": ok, "free": free, "has_free": bool(free), "free_json": json.dumps(free, separators=(",", ":")),
            "next_stage": "awaiting_time" if free else "awaiting_date", "reply": reply, "problem": problem}


def _month_of(today: str, off: int) -> dict:
    m0 = int(today[5:7]) - 1 + off
    y, m = int(today[:4]) + m0 // 12, m0 % 12
    return {"key": f"{y}-{m + 1:02d}", "name": MONTHS[m], "year": y}


def compute_available_dates(r: dict, events: list, holds: list, clinic: Clinic, now: int) -> dict:
    """Month step (month_offset = -1) or the free dates of this (0) / next (1) month."""
    step = int(clinic.booking["step_minutes"]) * MIN
    dur = (int(r.get("duration_min") or 30)) * MIN
    lead = int(clinic.booking["lead_minutes"]) * MIN
    events = active_events(events)
    holds = [x for x in holds if x and x.get("request_id")]
    blocks, bad = event_blocks(events, r.get("filter_by_name"), r["doctor_name"])
    held = held_intervals(holds, now, step, r.get("chat_id"))
    has_shift = bool(clinic.shift(r["doctor_key"]))
    today = ymd(now)
    today_ms = at(today, "12:00")

    def days_in(off):
        mk, out = _month_of(today, off), []
        if not has_shift or bad:
            return out
        for d in range(63):
            day = ymd(today_ms + d * DAY)
            if day[:7] != mk["key"]:
                continue
            window, _ = _day_window(clinic, r["doctor_key"], day)
            if not window:
                continue
            n, t = 0, window[0]
            while t + dur <= window[1]:
                if t >= now + lead and not _overlaps(blocks, t, dur) and not _overlaps(held, t, dur):
                    n += 1
                t += step
            if n:
                out.append({"date": day, "label": f"{MON[int(day[5:7]) - 1]} {int(day[8:10])} {SHORT_DAYS[weekday(day)]}", "free": n})
        return out

    visit = "Բժիշկ՝ " + r["doctor_name"] + "\nԱյց՝ " + (r.get("visit_label") or "—") + " (" + str(int(r.get("duration_min") or 30)) + " րոպե)"
    bad_reply = "Ներողություն, օրացույցում սխալ գրառում կա, և չեմ կարող ստուգել ազատ ժամերը։ Փորձեք ավելի ուշ։"
    m0, m1 = _month_of(today, 0), _month_of(today, 1)
    mo = r.get("month_offset", -1)
    if mo in (-1, None, ""):
        n0, n1 = len(days_in(0)), len(days_in(1))
        lab = lambda m, n: "📅 " + m["name"] + " " + str(m["year"]) + ("" if n else " (ազատ օր չկա)")
        return {"pick_month": True, "reply": bad_reply if bad else visit + "\n\nԸնտրեք ամիսը։",
                "month_labels": [lab(m0, n0), lab(m1, n1)], "has_dates": True, "labels": [], "toggle": ""}
    off = 1 if int(mo) == 1 else 0
    days = days_in(off)
    cur, other = (m0, m1) if off == 0 else (m1, m0)
    toggle = "📅 " + other["name"] + " →" if off == 0 else "← 📅 " + other["name"]
    if bad:
        reply = bad_reply
    elif days:
        reply = visit + "\n\n📅 " + cur["name"] + " " + str(cur["year"]) + "\nԸնտրեք ամսաթիվը ստորև․ ցուցադրված են միայն այն օրերը, երբ կա ազատ ժամ Ձեր այցի համար։"
    else:
        reply = visit + "\n\nՑավոք, " + cur["name"] + "ին ազատ ժամ չկա Ձեր այցի համար։\nՍեղմեք «" + toggle + "»՝ " + other["name"] + "ի օրերը տեսնելու համար, կամ «⬅️ Հետ»՝ այլ ամիս ընտրելու համար։"
    return {"pick_month": False, "reply": reply, "labels": [d["label"] for d in days[:24]], "has_dates": bool(days),
            "days": days, "toggle": toggle, "month_key": cur["key"], "month_labels": []}
