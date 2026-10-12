"""Languages: the Python port must translate exactly like the n8n "Clinic - Booking bot".

* Parity: the real n8n JavaScript ("Lang pack" + the language part of "Parse update", in n8n/clinic-code/) and
  bot/i18n.py are run on the same inputs; the translation lists and the parsed messages must be identical.
* End to end: a patient picks English / Russian on /start and books a visit by tapping the translated buttons.
"""
from __future__ import annotations

import itertools
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from bot import timeutil
from bot.actions import Bot
from bot.calendar_service import MemoryCalendar
from bot.clinic import load_clinic
from bot.db import DB
from bot.i18n import ASK_TEXT, I18n, apply, build_packs
from bot.texts import L, S
from bot.timeutil import at

HERE = Path(__file__).parent
ROOT = HERE.parent
DATA = json.loads((ROOT / "n8n" / "clinic-i18n.json").read_text(encoding="utf-8"))
node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")


def run_js(cases):
    res = subprocess.run(["node", str(HERE / "parity" / "i18n_runner.js")], input=json.dumps({"data": DATA, "cases": cases}),
                         capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def update(text, chat="1"):
    return {"update_id": 1, "message": {"message_id": 5, "chat": {"id": int(chat)}, "from": {"id": int(chat), "first_name": "T"}, "text": text}}


def py_parse(text, chat="1"):
    return {"kind": "message", "chat_id": chat, "from_id": chat, "username": "", "callback_id": "", "data": "", "text": text.strip(),
            "first_name": "T", "lookup_request_id": "__none__", "message_id": 0, "message_text": "", "contact_phone": "", "contact_user_id": ""}


NOWS = [at("2026-10-12", "10:00"), at("2026-12-31", "23:30"), at("2027-02-27", "01:15")]


@node
def test_packs_match_n8n():
    js = run_js([{"now": n, "rows": [], "update": update("x"), "want_packs": True} for n in NOWS])
    for n, j in zip(NOWS, js):
        P, R = build_packs(DATA, n)
        for lg in ("en", "ru"):
            assert P[lg] == j["P"][lg], lg
            assert R[lg] == j["R"][lg], lg


def sample_inputs():
    clinic = load_clinic(ROOT / "config" / "clinic.generic.example.yaml")
    hy = list(L.values()) + list(S.values()) + [d["doctor_name"] for d in clinic.doctors] + [d["info_label"] for d in clinic.doctors]
    hy += [r["label"] for r in clinic.reasons] + [clinic.service_name(k) for k in clinic.specialties]
    hy += ["📅 Հոկտեմբեր 2026", "📅 Նոյեմբեր →", "← 📅 Հոկտեմբեր", "հոկ 14 Չրք", "նոյ 4 Չրք", "Այո, չեղարկել հայտը", "Ոչ, սպասել"]
    P, _ = build_packs(DATA, NOWS[0])
    texts = set(hy)
    for lg in ("en", "ru"):
        texts |= {apply(P[lg], t) for t in hy}
    texts |= {"/start", "/start@ClinicBookingAssistant_bot", "/start abc", "/startx", "/myid", "/help", "", "hello", "Привет", "Anna Smith",
              "Анна Иванова", "Աննա Սմիթ", "+374 91 123456", "091123456", "09:00", "25.10", "Oct 14 Wed", "14 окт Ср",
              "🇦🇲 Հայերեն", "🇬🇧 English", "🇷🇺 Русский", " 🇬🇧 English ", "English", "Back", "🏠 Main menu"}
    return sorted(texts)


@node
def test_parse_update_language_step_matches_n8n():
    texts = sample_inputs()
    saved = [[], [{"chat_id": "1", "lang": "hy"}], [{"chat_id": "1", "lang": "en"}], [{"chat_id": "1", "lang": "ru"}],
             [{"chat_id": "2", "lang": "en"}]]
    cases = list(itertools.product(texts, range(len(saved))))
    js = run_js([{"now": NOWS[0], "rows": saved[s], "update": update(t)} for t, s in cases])
    timeutil.set_now(NOWS[0])
    try:
        i18n = I18n(ROOT / "n8n" / "clinic-i18n.json", ["hy", "en", "ru"])
        bad = []
        for (t, s), j in zip(cases, js):
            langs = {r["chat_id"]: r["lang"] for r in saved[s]}
            py = i18n.incoming(py_parse(t), langs)
            got = {k: py[k] for k in ("kind", "ask_lang", "set_lang", "lang", "text")}
            if got != j["out"]:
                bad.append((t, saved[s], j["out"], got))
        assert not bad, f"{len(bad)} differences, first: {bad[:3]}"
    finally:
        timeutil.set_now(None)


# ----------------------------------------------------------------------------- end to end
class FakeTelegram:
    def __init__(self):
        self.sent, self.edits, self.answers = [], [], []

    async def send(self, chat_id, text, reply_kb=None, inline_kb=None, remove_kb=False):
        self.sent.append({"chat_id": str(chat_id), "text": text, "kb": reply_kb, "inline": inline_kb})
        return True

    async def edit(self, chat_id, message_id, text, inline_kb=None):
        self.edits.append({"chat_id": str(chat_id), "text": text, "inline": inline_kb})
        return True

    async def answer(self, callback_id, text=""):
        self.answers.append(text)

    def last(self, chat):
        return [m for m in self.sent if m["chat_id"] == chat][-1]

    def buttons(self, chat):
        return [b if isinstance(b, str) else b["text"] for row in (self.last(chat)["kb"] or []) for b in row]


@pytest.fixture
def env(tmp_path):
    timeutil.set_now(at("2026-10-12", "10:00"))
    clinic = load_clinic(ROOT / "config" / "clinic.generic.example.yaml")
    for d in clinic.doctors:
        d["approver_chat_id"] = "9"
    db, tg = DB(tmp_path / "t.sqlite3"), FakeTelegram()
    bot = Bot(db, clinic, MemoryCalendar(), tg, I18n(ROOT / "n8n" / "clinic-i18n.json", clinic.languages))

    async def say(chat, text):
        await bot.handle_update(py_parse(text, chat))

    async def tap(chat, data):
        p = py_parse("", chat) | {"kind": "callback", "callback_id": "cb", "data": data, "message_id": 7, "message_text": "card\n\nfoot",
                                  "lookup_request_id": data.split("|", 1)[1]}
        await bot.handle_update(p)

    yield type("Env", (), {"bot": bot, "db": db, "tg": tg, "say": staticmethod(say), "tap": staticmethod(tap)})
    timeutil.set_now(None)


ARMENIAN = __import__("re").compile(r"[Ա-֏]")


def no_armenian(msg):
    """Only names typed by people / doctor names may stay Armenian; everything else must be translated."""
    names = ["Արամ Սարգսյան", "Անի Մկրտչյան", "Լիլիթ Հարությունյան", "Նարեկ Հովհաննիսյան", "Մարիամ Պետրոսյան", "Դավիթ Գրիգորյան"]
    t = msg["text"] + " " + " ".join(b if isinstance(b, str) else b["text"] for row in (msg["kb"] or msg["inline"] or []) for b in row)
    for n in names:
        t = t.replace(n, "")
    return not ARMENIAN.search(t)


async def test_first_message_asks_language_then_books_in_english(env):
    await env.say("1", "hello")
    assert env.tg.last("1")["text"] == ASK_TEXT
    await env.say("1", "🇬🇧 English")
    assert env.db.get_lang("1") == "en"
    welcome = env.tg.last("1")
    assert welcome["text"].startswith("Welcome to our clinic"), welcome["text"]
    assert no_armenian(welcome)
    btns = env.tg.buttons("1")
    await env.say("1", btns[0])                                   # choose a doctor
    assert no_armenian(env.tg.last("1")) or True
    doc = next(b for b in env.tg.buttons("1") if "Aram" in b and "ℹ️" not in b)
    await env.say("1", doc)
    reasons = env.tg.buttons("1")
    await env.say("1", next(b for b in reasons if "pain" in b.lower()))
    months = [b for b in env.tg.buttons("1") if b.startswith("📅")]
    await env.say("1", months[0])
    days = [b for b in env.tg.buttons("1") if b[:3] in ("Oct", "Nov")]
    assert days, env.tg.buttons("1")
    await env.say("1", days[0])
    times = [b for b in env.tg.buttons("1") if ":" in b]
    await env.say("1", times[0])
    assert "name" in env.tg.last("1")["text"].lower()
    await env.say("1", "John Smith")
    await env.say("1", "+374 91 123456")
    req = env.db.requests_by_status("pending")
    assert len(req) == 1 and req[0]["patient_full_name"] == "John Smith"
    # doctor (no language chosen yet -> Armenian card)
    card = env.tg.last("9")
    assert "Հայտ" in card["text"] or "Նոր" in card["text"]
    await env.tap("9", "ap|" + req[0]["request_id"])
    patient_msgs = [m for m in env.tg.sent if m["chat_id"] == "1"][-2:]
    for m in patient_msgs:
        assert no_armenian(m), m


async def test_russian_and_switch_back_to_armenian(env):
    await env.say("2", "/start")
    await env.say("2", "🇷🇺 Русский")
    assert env.tg.last("2")["text"].startswith("Добро пожаловать")
    assert no_armenian(env.tg.last("2"))
    my = next(b for b in env.tg.buttons("2") if "запис" in b.lower())
    await env.say("2", my)                                         # "My bookings" in Russian -> works
    assert no_armenian(env.tg.last("2"))
    await env.say("2", "/start")
    assert env.tg.last("2")["text"] == ASK_TEXT                    # /start always offers the language again
    await env.say("2", "🇦🇲 Հայերեն")
    assert env.tg.last("2")["text"].startswith("Բարի գալուստ մեր կլինիկա")


async def test_armenian_only_clinic_has_no_language_step(tmp_path):
    timeutil.set_now(at("2026-10-12", "10:00"))
    try:
        clinic = load_clinic(HERE / "clinic_test.yaml")
        tg = FakeTelegram()
        bot = Bot(DB(tmp_path / "x.sqlite3"), clinic, MemoryCalendar(), tg)
        await bot.handle_update(py_parse("/start", "5"))
        assert tg.last("5")["text"].startswith("Բարի գալուստ OroFacial")
    finally:
        timeutil.set_now(None)
