"""Smoke test: the Telegram application builds (no network calls) and keyboards convert correctly."""
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove

from bot.main import TelegramMessenger, build_application


def test_application_builds(monkeypatch, tmp_path):
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST-TOKEN")
    monkeypatch.setenv("CLINIC_CONFIG", "tests/clinic_test.yaml")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "db.sqlite3"))
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    app, settings = build_application()
    assert app.job_queue is not None and len(app.handlers[0]) == 2
    assert settings.webhook_url == ""


def test_keyboards():
    m = TelegramMessenger._reply_markup
    kb = m([["A", "B"], [{"text": "📱 share", "request_contact": True}], ["", ""]], None, False)
    assert isinstance(kb, ReplyKeyboardMarkup) and len(kb.keyboard) == 2 and kb.keyboard[1][0].request_contact
    ik = m(None, [[{"text": "ok", "callback_data": "ok|1"}, {"text": "map", "url": "https://example.com"}]], False)
    assert isinstance(ik, InlineKeyboardMarkup) and ik.inline_keyboard[0][1].url == "https://example.com"
    assert isinstance(m(None, None, True), ReplyKeyboardRemove)
    assert m(None, None, False) is None
