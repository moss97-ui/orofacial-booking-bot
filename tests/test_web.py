"""The patient app and the staff dashboard (bot/web.py), driven through their HTTP API.

Uses the bot's real booking engine with a fake Telegram and the in-memory calendar: a booking made in the app reaches
the doctor in Telegram, the doctor (or the dashboard) approves it, and the patient sees it in the app.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot import timeutil
from bot.actions import Bot
from bot.appdb import AppDB
from bot.calendar_service import MemoryCalendar
from bot.clinic import load_clinic
from bot.db import DB
from bot.jobs import run_scheduled
from bot.timeutil import DAY, HOUR, at, parse_ms
from bot.web import AppMessenger, WebApp

HERE = Path(__file__).parent
DOC = "9"


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, reply_kb=None, inline_kb=None, remove_kb=False):
        self.sent.append({"chat_id": str(chat_id), "text": text, "inline": inline_kb})
        return True

    async def edit(self, chat_id, message_id, text, inline_kb=None):
        return True

    async def answer(self, callback_id, text=""):
        return None


@pytest.fixture
async def app(tmp_path):
    timeutil.set_now(at("2026-10-12", "10:00"))
    clinic = load_clinic(HERE / "clinic_test.yaml")
    for d in clinic.doctors:
        d["approver_chat_id"] = DOC
    db = DB(tmp_path / "t.sqlite3")
    appdb = AppDB(db)
    tg = FakeTelegram()
    bot = Bot(db, clinic, MemoryCalendar(), AppMessenger(tg, appdb))
    webapp = WebApp(bot, appdb, tmp_path / "uploads", admin_password="secret-pass")
    client = TestClient(TestServer(webapp.build()))
    await client.start_server()
    yield type("A", (), {"c": client, "bot": bot, "db": db, "appdb": appdb, "tg": tg, "clinic": clinic})
    await client.close()
    timeutil.set_now(None)


async def j(resp, status=200):
    data = await resp.json()
    assert resp.status == status, (resp.status, data)
    return data


async def login(a, phone="091 123456", pin="1234", name="Աննա Պետրոսյան"):
    data = await j(await a.c.post("/api/auth", json={"phone": phone, "pin": pin, "name": name}))
    return {"Authorization": "Bearer " + data["token"]}


async def first_free(a, doctor="aram", reason="consult"):
    dates = await j(await a.c.get("/api/dates", params={"doctor": doctor, "reason": reason}))
    day = next(d for m in dates["months"] for d in m["days"])["date"]
    slots = await j(await a.c.get("/api/slots", params={"doctor": doctor, "reason": reason, "date": day}))
    return day, slots["times"]


async def test_pages_and_clinic_info(app):
    a = app
    assert (await a.c.get("/")).status == 200 and (await a.c.get("/admin")).status == 200
    info = await j(await a.c.get("/api/clinic"))
    assert info["name"] == "OroFacial" and len(info["doctors"]) >= 3 and info["services"]
    nf = await j(await a.c.get("/api/next-free"))
    assert nf["best"] and nf["best"]["date"] >= "2026-10-12"


async def test_account_pin_rules(app):
    a = app
    await j(await a.c.post("/api/auth", json={"phone": "091 123456", "pin": "12", "name": "Աննա Պետրոսյան"}), 400)
    await j(await a.c.post("/api/auth", json={"phone": "091 123456", "pin": "1234", "name": "x"}), 400)   # first time needs a full name
    h = await login(a)
    me = await j(await a.c.get("/api/me", headers=h))
    assert me["name"] == "Աննա Պետրոսյան" and me["phone"] == "+37491123456"
    await j(await a.c.post("/api/auth", json={"phone": "091123456", "pin": "9999"}), 401)                 # wrong PIN
    for _ in range(5):
        await a.c.post("/api/auth", json={"phone": "091123456", "pin": "9999"})
    await j(await a.c.post("/api/auth", json={"phone": "091123456", "pin": "1234"}), 429)                 # locked for a while
    await j(await a.c.get("/api/me"), 401)


async def test_book_in_app_doctor_approves_in_telegram(app):
    a = app
    h = await login(a)
    day, times = await first_free(a)
    res = await j(await a.c.post("/api/book", headers=h, json={"doctor": "aram", "reason": "consult", "date": day, "time": times[0]}))
    rid = res["id"]
    card = a.tg.sent[-1]
    assert card["chat_id"] == DOC and "հավելվածից" in card["text"] and card["inline"][0][0]["callback_data"] == "ap|" + rid
    # the same time is no longer offered, and booking it again fails
    _, again = await first_free(a)
    assert times[0] not in again
    h2 = await login(a, phone="093 111222", name="Դավիթ Սարգսյան")
    await j(await a.c.post("/api/book", headers=h2, json={"doctor": "aram", "reason": "consult", "date": day, "time": times[0]}), 409)
    # the doctor taps ✅ in Telegram
    await a.bot.handle_update({"kind": "callback", "chat_id": DOC, "from_id": DOC, "username": "", "callback_id": "c", "data": "ap|" + rid,
                               "text": "", "first_name": "", "lookup_request_id": rid, "message_id": 1, "message_text": card["text"],
                               "contact_phone": "", "contact_user_id": ""})
    me = await j(await a.c.get("/api/me", headers=h))
    assert me["upcoming"][0]["status"] == "approved" and me["unread"] >= 2
    notes = await j(await a.c.get("/api/notifications", headers=h))
    assert any("հաստատված" in n["text"] for n in notes)
    assert not [m for m in a.tg.sent if m["chat_id"].startswith("web:")]          # nothing went to Telegram for the app patient
    # reminder the day before arrives in the app; the patient confirms, then cancels -> the doctor is told
    timeutil.set_now(parse_ms(me["upcoming"][0]["date"] + "T" + me["upcoming"][0]["time"] + ":00+04:00") - 20 * HOUR)
    await run_scheduled(a.bot)
    me = await j(await a.c.get("/api/me", headers=h))
    assert me["upcoming"][0]["can_confirm"]
    await j(await a.c.post(f"/api/bookings/{rid}/confirm", headers=h))
    await j(await a.c.post(f"/api/bookings/{rid}/cancel", headers=h))
    assert a.db.get_request(rid)["status"] == "cancelled"
    assert "չեղարկեց" in a.tg.sent[-1]["text"] and a.tg.sent[-1]["chat_id"] == DOC
    # someone else's booking can't be touched
    await j(await a.c.post(f"/api/bookings/{rid}/cancel", headers=h2), 404)


async def test_rating_review_and_loyalty(app):
    a = app
    h = await login(a)
    day, times = await first_free(a)
    rid = (await j(await a.c.post("/api/book", headers=h, json={"doctor": "aram", "reason": "consult", "date": day, "time": times[0]})))["id"]
    adm = {"Authorization": "Bearer " + (await j(await a.c.post("/api/admin/login", json={"password": "secret-pass"})))["token"]}
    await j(await a.c.post(f"/api/admin/bookings/{rid}/approve", headers=adm))
    assert a.db.get_request(rid)["status"] == "approved"
    timeutil.set_now(parse_ms(a.db.get_request(rid)["slot_end"]) + 2 * HOUR)
    me = await j(await a.c.get("/api/me", headers=h))
    assert me["past"][0]["can_rate"] and me["loyalty"]["visits"] == 1
    await j(await a.c.post(f"/api/bookings/{rid}/rate", headers=h, json={"stars": 5, "review": "Շատ լավ բժիշկ"}))
    rev = await j(await a.c.get("/api/reviews"))
    assert rev["average"] == 5 and rev["reviews"][0]["text"] == "Շատ լավ բժիշկ" and rev["reviews"][0]["name"] == "Աննա Պ."
    await j(await a.c.post(f"/api/bookings/{rid}/rate", headers=h, json={"stars": 3}), 409)               # only once
    # the loyalty rule: every 2nd visit -> 15 % (set in the dashboard); the next booking gets it
    await j(await a.c.post("/api/admin/catalog", headers=adm, json={"loyalty": {"every": 2, "percent": 15}}))
    day, times = await first_free(a)
    res = await j(await a.c.post("/api/book", headers=h, json={"doctor": "aram", "reason": "consult", "date": day, "time": times[0]}))
    assert res["discount"] == 15 and "−15%" in a.tg.sent[-1]["text"]


async def test_promo_codes(app):
    a = app
    adm = {"Authorization": "Bearer " + (await j(await a.c.post("/api/admin/login", json={"password": "secret-pass"})))["token"]}
    await j(await a.c.post("/api/admin/promos", headers=adm, json={"code": "smile10", "percent": 10, "max_uses": 1}))
    assert (await j(await a.c.post("/api/promo/check", json={"code": "SMILE10"})))["percent"] == 10
    h = await login(a)
    day, times = await first_free(a)
    res = await j(await a.c.post("/api/book", headers=h, json={"doctor": "aram", "reason": "consult", "date": day, "time": times[0], "promo": "smile10"}))
    assert res["discount"] == 10 and "SMILE10" in a.tg.sent[-1]["text"]
    await j(await a.c.post("/api/promo/check", json={"code": "SMILE10"}), 404)                           # used up
    await j(await a.c.post("/api/book", headers=h, json={"doctor": "aram", "reason": "consult", "date": day, "time": times[1], "promo": "NOPE"}), 400)


async def test_dashboard(app):
    a = app
    await j(await a.c.post("/api/admin/login", json={"password": "wrong"}), 401)
    await j(await a.c.get("/api/admin/overview"), 401)
    h = await login(a)
    await j(await a.c.get("/api/admin/overview", headers=h), 401)                                          # a patient token is not enough
    adm = {"Authorization": "Bearer " + (await j(await a.c.post("/api/admin/login", json={"password": "secret-pass"})))["token"]}
    day, times = await first_free(a)
    rid = (await j(await a.c.post("/api/book", headers=h, json={"doctor": "aram", "reason": "consult", "date": day, "time": times[0]})))["id"]
    ov = await j(await a.c.get("/api/admin/overview", headers=adm))
    assert ov["stats"]["pending"] == 1 and ov["pending"][0]["source"] == "app" and ov["pending"][0]["phone"] == "+37491123456"
    await j(await a.c.post(f"/api/admin/bookings/{rid}/reject", headers=adm))
    assert a.db.get_request(rid)["status"] == "rejected"
    notes = await j(await a.c.get("/api/notifications", headers=h))
    assert any("չի կարող ընդունել" in n["text"] for n in notes)
    wk = await j(await a.c.get("/api/admin/bookings", headers=adm, params={"from": day, "days": 7}))
    assert any(b["id"] == rid for b in wk["bookings"])
    # block a day -> no free times that day
    await j(await a.c.post("/api/admin/blocks", headers=adm, json={"doctor": "aram", "date": day, "from": "00:00", "to": "23:59"}))
    assert (await j(await a.c.get("/api/slots", params={"doctor": "aram", "reason": "consult", "date": day})))["times"] == []
    blocks = await j(await a.c.get("/api/admin/blocks", headers=adm))
    await j(await a.c.delete(f"/api/admin/blocks/aram/{blocks[0]['id']}", headers=adm))
    assert (await j(await a.c.get("/api/slots", params={"doctor": "aram", "reason": "consult", "date": day})))["times"]
    # prices and bios: changed in the dashboard, seen by the app and the bot
    await j(await a.c.post("/api/admin/catalog", headers=adm, json={"reasons": {"consult": {"price": "6 000 ֏", "min": 45}},
                                                                   "doctors": {"aram": {"bio": "Նոր կենսագրություն"}}}))
    info = await j(await a.c.get("/api/clinic"))
    aram = next(d for d in info["doctors"] if d["key"] == "aram")
    assert aram["bio"] == "Նոր կենսագրություն" and next(r for r in aram["reasons"] if r["key"] == "consult")["price"] == "6 000 ֏"
    assert next(r for r in a.clinic.reasons if r["key"] == "consult")["min"] == 45
    await j(await a.c.post("/api/admin/catalog", headers=adm, json={"reasons": {"consult": {"min": 50}}}), 400)
    # photos: a portrait becomes the doctor's picture; work photos go to the gallery
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (40, 30), (200, 220, 230)).save(buf, "PNG")
    from aiohttp import FormData
    fd = FormData(); fd.add_field("file", buf.getvalue(), filename="a.png", content_type="image/png"); fd.add_field("kind", "portrait"); fd.add_field("doctor", "aram")
    up = await j(await a.c.post("/api/admin/photos", headers=adm, data=fd))
    assert (await a.c.get(up["url"])).status == 200
    info = await j(await a.c.get("/api/clinic"))
    assert next(d for d in info["doctors"] if d["key"] == "aram")["photo"] == up["url"]
    fd = FormData(); fd.add_field("file", b"not an image", filename="x.png", content_type="image/png")
    await j(await a.c.post("/api/admin/photos", headers=adm, data=fd), 400)
    await j(await a.c.delete(f"/api/admin/photos/{up['id']}", headers=adm))
    assert (await a.c.get(up["url"])).status == 404
    assert (await a.c.get("/uploads/../bot.sqlite3")).status == 404


async def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE requests (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT UNIQUE, chat_id TEXT, patient_name TEXT, "
                "patient_full_name TEXT, patient_phone TEXT, telegram_username TEXT, doctor_key TEXT, service TEXT, slot_start TEXT, slot_end TEXT, "
                "slot_key TEXT, status TEXT, expires_at TEXT, decided_by TEXT DEFAULT '', calendar_event_id TEXT DEFAULT '', replaces_request_id TEXT DEFAULT '', "
                "reminder_24h_sent INTEGER DEFAULT 0, reminder_2h_sent INTEGER DEFAULT 0, patient_confirmed TEXT DEFAULT '', rating INTEGER DEFAULT 0, "
                "rating_asked INTEGER DEFAULT 0, createdAt TEXT, updatedAt TEXT)")
    con.commit(); con.close()
    db = DB(path)
    db.insert_request({"request_id": "x", "chat_id": "web:1", "source": "app", "promo": "A", "discount": "10%"})
    assert db.get_request("x")["source"] == "app"
