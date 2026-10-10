"""End-to-end tests: the whole bot (router + actions + database + calendar) driven like real Telegram users.
Telegram and Google Calendar are replaced by in-memory fakes, so nothing is sent anywhere."""
from __future__ import annotations

from pathlib import Path

import pytest

from bot.actions import Bot
from bot.calendar_service import MemoryCalendar
from bot.clinic import load_clinic
from bot.db import DB
from bot.jobs import run_scheduled
from bot.router import route
from bot import timeutil
from bot.timeutil import HOUR, MIN, at

HERE = Path(__file__).parent
PATIENT, PATIENT2, STAFF = "1001", "1002", "9"


class FakeTelegram:
    def __init__(self):
        self.sent, self.edits, self.answers, self.fail_for = [], [], [], set()
        self._mid = 100

    async def send(self, chat_id, text, reply_kb=None, inline_kb=None, remove_kb=False):
        if str(chat_id) in self.fail_for:
            return False
        self._mid += 1
        self.sent.append({"chat_id": str(chat_id), "text": text, "kb": reply_kb, "inline": inline_kb, "message_id": self._mid})
        return True

    async def edit(self, chat_id, message_id, text, inline_kb=None):
        self.edits.append({"chat_id": str(chat_id), "message_id": message_id, "text": text, "inline": inline_kb})
        return True

    async def answer(self, callback_id, text=""):
        self.answers.append(text)

    def last(self, chat_id):
        return [m for m in self.sent if m["chat_id"] == str(chat_id)][-1]

    def buttons(self, chat_id):
        kb = self.last(chat_id)["kb"] or []
        return [b if isinstance(b, str) else b["text"] for row in kb for b in row]

    def inline_data(self, chat_id):
        return [b.get("callback_data") for row in (self.last(chat_id)["inline"] or []) for b in row]


@pytest.fixture
def env(tmp_path):
    timeutil.set_now(at("2026-10-12", "10:00"))  # Monday 10:00 Yerevan
    clinic = load_clinic(HERE / "clinic_test.yaml")
    db, cal, tg = DB(tmp_path / "t.sqlite3"), MemoryCalendar(), FakeTelegram()
    bot = Bot(db, clinic, cal, tg)

    async def say(chat, text, contact=None):
        p = {"kind": "message", "chat_id": chat, "from_id": chat, "username": "user" + chat, "callback_id": "", "data": "", "text": text,
             "first_name": "Test", "lookup_request_id": "__none__", "message_id": 0, "message_text": "",
             "contact_phone": contact or "", "contact_user_id": chat if contact else ""}
        out = route(p, db.get_session(chat), clinic, None, timeutil.now_ms())
        await bot.run(out, p)
        return out

    async def tap(chat, data, message_text="card\n\nfooter"):
        lookup = data.split("|", 1)[1] if "|" in data else "__none__"
        p = {"kind": "callback", "chat_id": chat, "from_id": chat, "username": "", "callback_id": "cb", "data": data, "text": "", "first_name": "",
             "lookup_request_id": lookup, "message_id": 55, "message_text": message_text, "contact_phone": "", "contact_user_id": ""}
        out = route(p, db.get_session(chat), clinic, db.get_request(lookup), timeutil.now_ms())
        await bot.run(out, p)
        return out

    yield type("Env", (), {"bot": bot, "db": db, "cal": cal, "tg": tg, "say": staticmethod(say), "tap": staticmethod(tap), "clinic": clinic})
    timeutil.set_now(None)


async def book(env, chat=PATIENT, doctor="Արամ Սարգսյան", reason="⚡ Սուր ցավ", month="📅 Հոկտեմբեր 2026", day="հոկ 14 Չրք", time="09:00",
               name="Գոռ Պետրոսյան", phone="091 123456"):
    await env.say(chat, "/start")
    await env.say(chat, "👨‍⚕️ Ընտրել բժիշկ")
    await env.say(chat, doctor)
    await env.say(chat, reason)
    await env.say(chat, month)
    assert day in env.tg.buttons(chat), env.tg.buttons(chat)
    await env.say(chat, day)
    assert time in env.tg.buttons(chat), env.tg.buttons(chat)
    await env.say(chat, time)
    if name:
        await env.say(chat, name)
        await env.say(chat, phone)
    return env.db.get_session(chat)["request_id"]


async def test_full_booking_and_approval(env):
    rid = await book(env)
    req = env.db.get_request(rid)
    assert req["status"] == "pending" and req["slot_end"] == "2026-10-14T09:30:00+04:00" and req["patient_phone"] == "+37491123456"
    doctor_msg = env.tg.last(STAFF)
    assert doctor_msg["text"].startswith("🦷 Նոր ամրագրման հայտ") and env.tg.inline_data(STAFF) == ["ap|" + rid, "rj|" + rid]
    assert "Ձեր հայտն ուղարկվեց բժշկին" in env.tg.sent[-1]["text"]
    await env.tap(STAFF, "ap|" + rid, doctor_msg["text"])
    req = env.db.get_request(rid)
    assert req["status"] == "approved" and req["calendar_event_id"]
    assert env.cal.events["shared-cal"][0]["summary"].startswith("Արամ Սարգսյան — Սուր ցավ")
    patient_msgs = [m["text"] for m in env.tg.sent if m["chat_id"] == PATIENT]
    assert any(t.startswith("✅ Ձեր այցը հաստատված է։") for t in patient_msgs)
    assert any(t.startswith("📍 Ինչպես հասնել կլինիկա") for t in patient_msgs)
    assert env.tg.edits[-1]["text"].endswith("✅ Հաստատված է։ Այցը ստեղծվեց օրացույցում, պացիենտը տեղեկացվել է։")
    # second tap on the same request does nothing
    await env.tap(STAFF, "ap|" + rid, doctor_msg["text"])
    assert "արդեն մշակված" in env.tg.answers[-1]
    # the booked time is no longer offered to another patient
    await book(env, chat=PATIENT2, time="09:30", name=None)
    assert "09:00" not in env.tg.buttons(PATIENT2)


async def test_reject_offers_other_times_and_hides_rejected_time(env):
    rid = await book(env)
    await env.tap(STAFF, "rj|" + rid)
    assert env.db.get_request(rid)["status"] == "rejected"
    assert env.tg.last(PATIENT)["text"].startswith("Ցավոք, բժիշկը չի կարող ընդունել Ձեզ")
    await env.say(PATIENT, "🕐 Այլ ժամ")
    assert "09:00" not in env.tg.buttons(PATIENT) and "09:30" in env.tg.buttons(PATIENT)
    # quick rebook reuses the saved name and phone
    await env.say(PATIENT, "09:30")
    new = env.db.get_session(PATIENT)["request_id"]
    assert new != rid and env.db.get_request(new)["patient_phone"] == "+37491123456"


async def test_double_booking_conflict(env):
    # patient 2 sees the free times first ...
    await env.say(PATIENT2, "/start"); await env.say(PATIENT2, "👨‍⚕️ Ընտրել բժիշկ"); await env.say(PATIENT2, "Արամ Սարգսյան")
    await env.say(PATIENT2, "⚡ Սուր ցավ"); await env.say(PATIENT2, "📅 Հոկտեմբեր 2026"); await env.say(PATIENT2, "հոկ 14 Չրք")
    assert "09:00" in env.tg.buttons(PATIENT2)
    # ... then patient 1 books 09:00, and only afterwards patient 2 taps the same time
    rid1 = await book(env)
    await env.say(PATIENT2, "09:00")
    await env.say(PATIENT2, "Անի Պետրոսյան")
    await env.say(PATIENT2, "+374 99 112233")
    assert env.db.get_session(PATIENT2).get("request_id", "") == ""
    assert any("այլևս ազատ չէ" in m["text"] for m in env.tg.sent if m["chat_id"] == PATIENT2)
    assert env.db.get_request(rid1)["status"] == "pending"


async def test_cancel_notifies_waitlist(env):
    rid = await book(env)
    await env.tap(STAFF, "ap|" + rid)
    # patient 2 joins the waitlist for Aram on the day picker
    await env.say(PATIENT2, "/start"); await env.say(PATIENT2, "👨‍⚕️ Ընտրել բժիշկ"); await env.say(PATIENT2, "Արամ Սարգսյան")
    await env.say(PATIENT2, "⚡ Սուր ցավ"); await env.say(PATIENT2, "📅 Հոկտեմբեր 2026")
    await env.say(PATIENT2, "🔔 Սպասման ցուցակ")
    assert env.tg.last(PATIENT2)["text"].startswith("🔔 Դուք ավելացվեցիք սպասման ցուցակում")
    # patient 1 cancels from a reminder card ("❌ Չեմ կարող գալ" -> confirm)
    await env.tap(PATIENT, "cx|" + rid)
    assert env.tg.edits[-1]["inline"][0][0]["callback_data"] == "cy|" + rid
    await env.tap(PATIENT, "cy|" + rid)
    assert env.db.get_request(rid)["status"] == "cancelled" and env.cal.events["shared-cal"] == []
    assert env.tg.last(STAFF)["text"].startswith("❌ Պացիենտը չեղարկեց ամրագրումը")
    note = env.tg.last(PATIENT2)
    assert note["text"].startswith("🔔 Լավ լուր․ ժամ է ազատվել") and note["kb"][0] == ["Արամ Սարգսյան"]
    assert env.db.waiting_for_doctor("aram") == []


async def test_time_change(env):
    rid = await book(env)
    await env.tap(STAFF, "ap|" + rid)
    await env.tap(PATIENT, "ch|" + rid)
    assert env.db.get_session(PATIENT)["replace_request_id"] == rid
    await env.say(PATIENT, "📅 Հոկտեմբեր 2026")
    await env.say(PATIENT, "հոկ 15 Հնգ")
    await env.say(PATIENT, "10:00")  # name and phone are reused
    new = env.db.get_session(PATIENT)["request_id"]
    assert env.tg.last(STAFF)["text"].startswith("🔁 Ժամի փոփոխության հայտ\nՆախկին ժամ՝ 2026-10-14, 09:00")
    await env.tap(STAFF, "ap|" + new)
    assert env.db.get_request(rid)["status"] == "cancelled" and env.db.get_request(new)["status"] == "approved"
    assert len(env.cal.events["shared-cal"]) == 1
    assert any(m["text"].startswith("🔁 Ձեր այցի ժամը փոխված է։\nՁեր 2026-10-14, 09:00-ի այցը տեղափոխվել է 2026-10-15, 10:00") for m in env.tg.sent)


async def test_staff_block_and_unblock(env):
    await env.say(STAFF, "🚫 Փակել օր / ժամ")
    assert "Արամ Սարգսյան" in env.tg.buttons(STAFF)
    await env.say(STAFF, "Արամ Սարգսյան")
    await env.say(STAFF, "հոկ 14 Չրք")
    await env.say(STAFF, "🌅 09:00–13:00")
    ev = env.cal.events["shared-cal"][0]
    assert ev["summary"] == "⛔ Փակ — Արամ Սարգսյան" and ev["start"]["dateTime"] == "2026-10-14T09:00:00+04:00"
    undo = [m for m in env.tg.sent if m["chat_id"] == STAFF and m["inline"]][-1]
    assert undo["inline"][0][0]["callback_data"] == "ub|aram|" + ev["id"]
    # patients no longer see the morning
    await book(env, chat=PATIENT, time="13:00", name=None)
    assert "09:00" not in env.tg.buttons(PATIENT)
    await env.tap(STAFF, "ub|aram|" + ev["id"], undo["text"])
    assert env.cal.events["shared-cal"] == [] and "Փակումը չեղարկվեց" in env.tg.edits[-1]["text"]


async def test_reminders_and_rating(env):
    rid = await book(env)
    await env.tap(STAFF, "ap|" + rid)
    # day before
    timeutil.set_now(at("2026-10-13", "12:00"))
    env.db.conn.execute("UPDATE requests SET createdAt = '2026-10-11T00:00:00.000Z'")
    assert (await run_scheduled(env.bot))["reminders"] == 1
    assert env.tg.last(PATIENT)["text"].startswith("⏰ Հիշեցում՝ վաղը Ձեր այցն է")
    assert env.tg.inline_data(PATIENT)[:3] == ["ok|" + rid, "cx|" + rid, "ch|" + rid]
    # two hours before
    timeutil.set_now(at("2026-10-14", "07:30"))
    assert (await run_scheduled(env.bot))["reminders"] == 1
    assert (await run_scheduled(env.bot))["reminders"] == 0
    await env.tap(PATIENT, "ok|" + rid)
    assert env.db.get_request(rid)["patient_confirmed"]
    # after the visit: rating request, then a low rating alerts staff
    timeutil.set_now(at("2026-10-14", "10:15"))
    assert (await run_scheduled(env.bot))["ratings"] == 1
    assert env.tg.inline_data(PATIENT) == [f"r{i}|{rid}" for i in range(1, 6)]
    await env.tap(PATIENT, "r2|" + rid, "🦷 Ինչպե՞ս անցավ\nԲժիշկ\n\nԽնդրում ենք")
    assert env.db.get_request(rid)["rating"] == 2
    assert env.tg.last(STAFF)["text"].startswith("⚠️ Ցածր գնահատական՝ 2/5")
    await env.tap(PATIENT, "r5|" + rid)
    assert env.db.get_request(rid)["rating"] == 2


async def test_staff_report_and_menus(env):
    rid = await book(env)
    await env.say(STAFF, "⏳ Սպասող հայտեր")
    cards = [m for m in env.tg.sent if m["chat_id"] == STAFF and m["inline"]]
    assert cards[-1]["inline"][0][0]["callback_data"] == "ap|" + rid
    await env.say(STAFF, "📊 Վահանակ")
    assert "⏳ Սպասող հայտեր՝ 1" in [m for m in env.tg.sent if m["chat_id"] == STAFF][-1]["text"]
    await env.say(PATIENT, "📞 Կապ կլինիկայի հետ")
    assert "+374 10 529529" in env.tg.last(PATIENT)["text"]
    await env.say(PATIENT, "ℹ️ Դավթի մասին")
    assert "25 000 ֏-ից" in env.tg.last(PATIENT)["text"]


async def test_calendar_down_and_doctor_unreachable(env):
    await env.say(PATIENT, "/start"); await env.say(PATIENT, "👨‍⚕️ Ընտրել բժիշկ"); await env.say(PATIENT, "Արամ Սարգսյան")
    env.cal.fail = True
    await env.say(PATIENT, "⚡ Սուր ցավ")
    assert env.tg.last(PATIENT)["text"].startswith("⚠️ Ներողություն, օրացույցը հիմա հասանելի չէ")
    env.cal.fail = False
    env.tg.fail_for.add(STAFF)
    rid = await book(env)
    assert env.db.get_request(rid)["status"] == "failed"
    assert env.tg.last(PATIENT)["text"].startswith("Ներողություն, չհաջողվեց հայտը փոխանցել բժշկին")
