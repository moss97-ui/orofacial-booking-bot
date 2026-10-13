"""Entry point: python -m bot.main

Runs the Telegram bot with long polling (simplest, works behind any firewall) or, if WEBHOOK_URL is set,
with a webhook (better for servers with a public HTTPS address). Reminders run every 30 minutes.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
                      Update)
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from .actions import Bot
from .appdb import AppDB
from .calendar_service import GoogleCalendar, MemoryCalendar
from .clinic import load_clinic
from .config import load_settings
from .db import DB
from .i18n import I18n
from .jobs import run_scheduled

log = logging.getLogger("clinic-bot")


class TelegramMessenger:
    """Sends messages through python-telegram-bot. Keyboards come in as plain lists from actions.py."""

    def __init__(self, application: Application):
        self.app = application

    @staticmethod
    def _reply_markup(reply_kb, inline_kb, remove_kb):
        if remove_kb:
            return ReplyKeyboardRemove()
        if inline_kb is not None:
            return InlineKeyboardMarkup([[InlineKeyboardButton(b["text"], url=b.get("url"), callback_data=b.get("callback_data"))
                                          for b in row] for row in inline_kb])
        if reply_kb:
            rows = []
            for row in reply_kb:
                rows.append([KeyboardButton(b["text"], request_contact=b.get("request_contact", False)) if isinstance(b, dict)
                             else KeyboardButton(b) for b in row if b])
            return ReplyKeyboardMarkup([r for r in rows if r], resize_keyboard=True)
        return None

    async def send(self, chat_id, text, reply_kb=None, inline_kb=None, remove_kb=False) -> bool:
        if not chat_id:
            return False
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text, reply_markup=self._reply_markup(reply_kb, inline_kb, remove_kb))
            return True
        except TelegramError as e:
            log.warning("send to %s failed: %s", chat_id, e)
            return False

    async def edit(self, chat_id, message_id, text, inline_kb=None) -> bool:
        try:
            markup = self._reply_markup(None, inline_kb, False) if inline_kb else None
            await self.app.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup)
            return True
        except TelegramError as e:
            log.warning("edit failed: %s", e)
            return False

    async def answer(self, callback_id, text="") -> None:
        if not callback_id:
            return
        try:
            await self.app.bot.answer_callback_query(callback_id, text=text or None)
        except TelegramError as e:
            log.debug("answer callback failed: %s", e)


def parse_update(update: Update) -> dict:
    """Same fields as the n8n "Parse update" node."""
    if update.callback_query:
        cq = update.callback_query
        msg = cq.message
        data = cq.data or ""
        mm = re.fullmatch(r"(ap|rj|cx|cy|nx|ch|ok|r[1-5]|ub)\|(.{1,60})", data)  # same rule as n8n
        lookup = mm.group(2) if mm else "__none__"
        return {"kind": "callback", "chat_id": str(msg.chat.id if msg else cq.from_user.id), "from_id": str(cq.from_user.id),
                "username": cq.from_user.username or "", "callback_id": cq.id, "data": data, "text": "",
                "first_name": cq.from_user.first_name or "", "lookup_request_id": lookup,
                "message_id": msg.message_id if msg else 0, "message_text": (getattr(msg, "text", None) or "") if msg else "",
                "contact_phone": "", "contact_user_id": ""}
    m = update.effective_message
    c = m.contact if m else None
    return {"kind": "message", "chat_id": str(m.chat.id) if m else "", "from_id": str(m.from_user.id) if m and m.from_user else "",
            "username": (m.from_user.username or "") if m and m.from_user else "", "callback_id": "", "data": "",
            "text": (m.text or "").strip() if m else "", "first_name": (m.from_user.first_name or "") if m and m.from_user else "",
            "lookup_request_id": "__none__", "message_id": 0, "message_text": "",
            "contact_phone": str(c.phone_number or "") if c else "", "contact_user_id": str(c.user_id) if c and c.user_id else ""}


def build_application():
    settings = load_settings()
    # stdout, so hosting dashboards (Railway) show normal lines as info, not as errors
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    # The HTTP client logs every request URL, and Telegram URLs contain the bot token: keep those lines out of the log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    clinic = load_clinic(settings.clinic_config)
    db = DB(settings.database_path)
    if settings.google_service_account_file:
        calendar = GoogleCalendar(settings.google_service_account_file)
    else:
        log.warning("GOOGLE_SERVICE_ACCOUNT_FILE is not set: DRY RUN with an in-memory calendar (nothing is written to Google Calendar).")
        calendar = MemoryCalendar()

    if any(str(d["calendar_id"]).startswith("REPLACE_WITH") for d in clinic.active_doctors()) and settings.google_service_account_file:
        log.warning("Some doctors still have a placeholder calendar_id. Set CALENDAR_ID or edit the clinic config.")
    if any(str(d["approver_chat_id"]).startswith("REPLACE_WITH") for d in clinic.active_doctors()):
        log.warning("Some doctors still have a placeholder approver_chat_id. Set APPROVER_CHAT_ID or edit the clinic config.")
    i18n = I18n(settings.i18n_file, clinic.languages)
    if i18n.enabled:
        log.info("Languages: %s (language choice on /start)", ", ".join(clinic.languages))

    app = Application.builder().token(settings.telegram_token).build()
    appdb = AppDB(db)
    # App patients (chat "web:<id>") get in-app notifications; everyone else gets Telegram messages.
    from .web import AppMessenger
    bot = Bot(db, clinic, calendar, AppMessenger(TelegramMessenger(app), appdb), i18n)
    app.bot_data["clinic_bot"], app.bot_data["appdb"] = bot, appdb
    # One update at a time per chat keeps sessions consistent; different chats run concurrently.
    locks: dict[str, asyncio.Lock] = {}

    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
        p = parse_update(update)
        key = p["chat_id"] or "?"
        async with locks.setdefault(key, asyncio.Lock()):
            try:
                await bot.handle_update(p)
            except Exception:
                log.exception("update failed: %s", p)

    async def scheduled(context: ContextTypes.DEFAULT_TYPE):
        try:
            await run_scheduled(bot)
        except Exception:
            log.exception("scheduled run failed")

    app.add_handler(CallbackQueryHandler(handle))
    app.add_handler(MessageHandler(filters.TEXT | filters.CONTACT | filters.COMMAND, handle))
    app.job_queue.run_repeating(scheduled, interval=settings.reminder_interval_minutes * 60, first=30)
    return app, settings


async def run_polling_with_web(app, settings):
    """Long polling for Telegram plus the patient app / staff dashboard on PORT, in one process."""
    from aiohttp import web as aioweb

    from .web import WebApp
    webapp = WebApp(app.bot_data["clinic_bot"], app.bot_data["appdb"], settings.uploads_dir, settings.admin_password)
    runner = aioweb.AppRunner(webapp.build(), access_log=None)
    await runner.setup()
    await aioweb.TCPSite(runner, "0.0.0.0", settings.port).start()
    log.info("App on port %s (patients: /, staff: /admin%s)", settings.port, "" if settings.admin_password else " — set ADMIN_PASSWORD to enable")
    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=["message", "callback_query"])
        log.info("Starting long polling")
        try:
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.stop()
            await runner.cleanup()


def main():
    app, settings = build_application()
    updates = ["message", "callback_query"]
    if settings.webhook_url:
        log.info("Starting webhook on port %s -> %s", settings.port, settings.webhook_url)
        app.run_webhook(listen="0.0.0.0", port=settings.port, url_path="telegram", webhook_url=settings.webhook_url.rstrip("/") + "/telegram",
                        secret_token=settings.webhook_secret or None, allowed_updates=updates, drop_pending_updates=False)
    elif settings.web_app:
        asyncio.run(run_polling_with_web(app, settings))
    else:
        log.info("Starting long polling")
        app.run_polling(allowed_updates=updates)


if __name__ == "__main__":
    main()
