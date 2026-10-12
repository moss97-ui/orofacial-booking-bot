"""Beauty-salon mode (config/salon.example.yaml): the same booking engine with salon wording, services and Saturday hours.

Drives the whole bot like real clients and a salon admin, in Armenian, English and Russian, and checks every message:
no clinic words (doctor / patient / clinic / medical / tooth) in any language, and no untranslated Armenian in
English or Russian messages.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from bot import timeutil
from bot.actions import Bot
from bot.calendar_service import MemoryCalendar
from bot.clinic import load_clinic
from bot.db import DB
from bot.i18n import ASK_TEXT, I18n
from bot.jobs import run_scheduled
from bot.texts import L, S
from bot.timeutil import DAY, HOUR, MIN, at, weekday

from tests.test_i18n import FakeTelegram, py_parse

ROOT = Path(__file__).parent.parent
CLIENT, ADMIN = "501", "9"
CLINIC_WORDS = re.compile(r"բժիշկ|բժշկ|Բժիշկ|Բժշկ|պացիենտ|Պացիենտ|կլինիկ|Կլինիկ|ատամ|"
                          r"[Dd]octor|[Pp]atient|[Cc]linic|[Mm]edical|[Dd]ental|[Tt]ooth|[Tt]eeth|"
                          r"врач|Врач|пациент|Пациент|клиник|Клиник|медицин|зуб|🦷|👨‍⚕️|🩺")
ARMENIAN = re.compile(r"[Ա-֏]")
LANG_BTN = {"hy": "🇦🇲 Հայերեն", "en": "🇬🇧 English", "ru": "🇷🇺 Русский"}


def make_bot(tmp_path):
    clinic = load_clinic(ROOT / "config" / "salon.example.yaml")
    for d in clinic.doctors:
        d["approver_chat_id"] = ADMIN
        d["calendar_id"] = "salon@group.calendar.google.com"
    tg = FakeTelegram()
    i18n = I18n(ROOT / "n8n" / "clinic-i18n.json", clinic.languages, extra=ROOT / clinic.i18n_extra, vocab=ROOT / clinic.vocabulary,
                labels=list(L.values()) + list(S.values()))
    bot = Bot(DB(tmp_path / "salon.sqlite3"), clinic, MemoryCalendar(), tg, i18n)
    return bot, tg, clinic


def texts_of(tg, chat=None):
    out = [m["text"] + " " + " ".join(b if isinstance(b, str) else b["text"] for row in (m["kb"] or m["inline"] or []) for b in row)
           for m in tg.sent if chat is None or m["chat_id"] == chat]
    out += [e["text"] + " " + " ".join(b["text"] for row in (e["inline"] or []) for b in row) for e in tg.edits if chat is None or e["chat_id"] == chat]
    return out + [a for a in tg.answers if a]


class Session:
    def __init__(self, bot, tg):
        self.bot, self.tg = bot, tg

    async def say(self, chat, text):
        await self.bot.handle_update(py_parse(text, chat))

    async def tap(self, chat, data):
        p = py_parse("", chat) | {"kind": "callback", "callback_id": "cb", "data": data, "message_id": 7, "message_text": "card\n\nfoot",
                                  "lookup_request_id": data.split("|", 1)[1]}
        await self.bot.handle_update(p)

    def btns(self, chat):
        return self.tg.buttons(chat)

    async def press(self, chat, pick):
        """Tap the first reply button for which pick(label) is true."""
        b = next(x for x in self.btns(chat) if pick(x))
        await self.say(chat, b)
        return b


async def full_journey(bot, tg, clinic, lang):
    s = Session(bot, tg)
    # admin picks a language too (approvals and lists then come in that language)
    await s.say(ADMIN, "/start"); await s.say(ADMIN, LANG_BTN[lang])
    admin_menu = list(s.btns(ADMIN))
    for b in list(s.btns(ADMIN)):
        if b.startswith(("📊", "📅", "📆", "🗓", "⏳", "❓")):
            await s.say(ADMIN, b)
    # client
    await s.say(CLIENT, "hello")
    assert tg.last(CLIENT)["text"] == ASK_TEXT
    await s.say(CLIENT, LANG_BTN[lang])
    welcome = s.btns(CLIENT)
    for b in welcome:
        if b.startswith(("❓", "📞")):
            await s.say(CLIENT, b)
    await s.say(CLIENT, welcome[0])                                  # choose a specialist
    for b in [x for x in s.btns(CLIENT) if x.startswith("ℹ️")]:      # every profile
        await s.say(CLIENT, b)
    # every service category, then back
    for i in range(len(clinic.service_menu)):
        await s.say(CLIENT, welcome[1])
        await s.say(CLIENT, s.btns(CLIENT)[i])
        names = [x for x in s.btns(CLIENT) if not x.startswith(("ℹ️", "⬅️", "🏠"))]
        assert names, (lang, i, s.btns(CLIENT))
        await s.say(CLIENT, names[0])                               # specialist -> services
        assert len(s.btns(CLIENT)) >= 3
        await s.say(CLIENT, next(x for x in s.btns(CLIENT) if x.startswith("⬅️")))
    # book with the nail master on a Saturday
    await s.say(CLIENT, welcome[0])
    ani = clinic.doctors[2]
    await s.press(CLIENT, lambda x: not x.startswith("ℹ️") and ("Ani" in x or "Ани" in x or "Անի" in x))
    await s.press(CLIENT, lambda x: "💅" in x)                       # manicure
    await s.press(CLIENT, lambda x: x.startswith("📅"))               # this month
    days = [x for x in s.btns(CLIENT) if re.search(r"\d", x) and not x.startswith(("📅", "←", "🔔"))]
    sat = {"hy": "Շբթ", "en": "Sat", "ru": "Сб"}[lang]
    assert any(sat in d for d in days), (lang, days)                  # Saturdays are offered
    await s.say(CLIENT, next(d for d in days if sat in d))
    times = [x for x in s.btns(CLIENT) if re.fullmatch(r"\d\d:\d\d", x)]
    assert times and times[-1] <= "15:00", times                     # Saturday shift 10:00–16:00, 60-min manicure
    await s.say(CLIENT, times[0])
    await s.say(CLIENT, {"hy": "Աննա Պետրոսյան", "en": "Anna Smith", "ru": "Анна Смирнова"}[lang])
    await s.say(CLIENT, "+374 91 123456")
    req = bot.db.requests_by_status("pending")
    assert len(req) == 1 and weekday(req[0]["slot_start"][:10]) == 6
    await s.tap(ADMIN, "ap|" + req[0]["request_id"])
    assert bot.db.get_request(req[0]["request_id"])["status"] == "approved"
    await s.say(CLIENT, welcome[2])                                  # my bookings
    # waitlist from the date list of another specialist
    await s.say(CLIENT, welcome[0])
    await s.press(CLIENT, lambda x: not x.startswith("ℹ️") and ("Lilit" in x or "Лилит" in x or "Լիլիթ" in x))
    await s.press(CLIENT, lambda x: "🍃" in x)
    await s.press(CLIENT, lambda x: x.startswith("📅"))
    await s.press(CLIENT, lambda x: x.startswith("🔔"))
    # reminder the day before, confirm; rating after; low rating alerts the admin
    start = timeutil.parse_ms(req[0]["slot_start"])
    timeutil.set_now(start - 20 * HOUR)
    await run_scheduled(bot)
    await s.tap(CLIENT, "ok|" + req[0]["request_id"])
    timeutil.set_now(start + 3 * HOUR)
    await run_scheduled(bot)
    await s.tap(CLIENT, "r2|" + req[0]["request_id"])
    # admin: block a Saturday for the barber, then undo
    timeutil.set_now(at("2026-10-12", "10:00"))
    await s.say(ADMIN, next(x for x in admin_menu if x.startswith("🚫")))
    await s.press(ADMIN, lambda x: "Arman" in x or "Арман" in x or "Արման" in x)
    blk = [x for x in s.btns(ADMIN) if sat in x]
    assert blk, s.btns(ADMIN)                                         # the barber works Saturdays -> offered
    await s.say(ADMIN, blk[0])
    await s.press(ADMIN, lambda x: x.startswith("🚫"))
    undo = [d for d in tg.sent[-1]["inline"] or [[]] for d in d if d.get("callback_data", "").startswith("ub|")]
    if undo:
        await s.tap(ADMIN, undo[0]["callback_data"])
    # second booking, then cancel it from "my bookings" -> waitlisted client notified, admin told
    return s


@pytest.mark.parametrize("lang", ["hy", "en", "ru"])
async def test_salon_journey_has_salon_wording_only(tmp_path, lang):
    timeutil.set_now(at("2026-10-12", "10:00"))
    try:
        bot, tg, clinic = make_bot(tmp_path)
        await full_journey(bot, tg, clinic, lang)
        msgs = [m for m in texts_of(tg) if m != ASK_TEXT + " " + " ".join(LANG_BTN.values())]
        assert len(msgs) > 60, len(msgs)
        leaks = [m for m in msgs if CLINIC_WORDS.search(m)]
        assert not leaks, f"{len(leaks)} messages with clinic words, e.g. {leaks[:3]}"
        if lang != "hy":
            arm = [m for m in msgs if ARMENIAN.search(m.replace(ASK_TEXT, ""))]
            assert not arm, f"{len(arm)} untranslated, e.g. {arm[:3]}"
    finally:
        timeutil.set_now(None)


async def test_cancel_notifies_waitlist_in_salon_wording(tmp_path):
    timeutil.set_now(at("2026-10-12", "10:00"))
    try:
        bot, tg, clinic = make_bot(tmp_path)
        s = Session(bot, tg)
        for chat, lg in [(CLIENT, "en"), ("502", "ru"), (ADMIN, "hy")]:
            await s.say(chat, "/start"); await s.say(chat, LANG_BTN[lg])
        await s.say(CLIENT, s.btns(CLIENT)[0])
        await s.press(CLIENT, lambda x: x == "Arman Hakobyan")
        await s.press(CLIENT, lambda x: x.startswith("💈 Men"))
        await s.press(CLIENT, lambda x: x.startswith("📅"))
        await s.say(CLIENT, [x for x in s.btns(CLIENT) if re.search(r"\d", x) and not x.startswith(("📅", "←", "🔔"))][0])
        await s.say(CLIENT, [x for x in s.btns(CLIENT) if re.fullmatch(r"\d\d:\d\d", x)][0])
        await s.say(CLIENT, "John Smith"); await s.say(CLIENT, "+374 91 123456")
        rid = bot.db.requests_by_status("pending")[0]["request_id"]
        await s.tap(ADMIN, "ap|" + rid)
        # the Russian client joins the barber's waitlist
        await s.say("502", s.btns("502")[0])
        await s.press("502", lambda x: x == "Арман Акопян")
        await s.press("502", lambda x: x.startswith("💈 Мужская"))
        await s.press("502", lambda x: x.startswith("📅"))
        await s.press("502", lambda x: x.startswith("🔔"))
        await s.tap(CLIENT, "cx|" + rid); await s.tap(CLIENT, "cy|" + rid)
        assert bot.db.get_request(rid)["status"] == "cancelled"
        ru = tg.last("502")["text"]
        assert "освободилось время" in ru and "Мастер: Арман Акопян" in ru and not ARMENIAN.search(ru), ru
        admin = " ".join(texts_of(tg, ADMIN))
        assert "հաճախորդ" in admin.lower() and not CLINIC_WORDS.search(admin)
    finally:
        timeutil.set_now(None)


def test_clinic_texts_unchanged_without_vocabulary():
    """The clinic setup (no vocabulary file) still says doctor / patient / clinic."""
    i18n = I18n(ROOT / "n8n" / "clinic-i18n.json", ["hy", "en", "ru"])
    assert i18n.translate(L["chooseDoctor"], "en") == "👨‍⚕️ Choose a doctor"
    assert i18n.translate(L["chooseDoctor"], "hy") == L["chooseDoctor"]
