"""Storage for the patient app and the staff dashboard (same SQLite file as the bot).

accounts       patients who use the app (phone + PIN). Their bookings use chat_id "web:<account id>".
tokens         sign-in tokens (patients and staff).
notifications  messages for app patients (what a Telegram patient would get as a chat message).
promos         promo codes.
photos         photos uploaded by staff (doctor portraits, work, the clinic).
settings       values staff change in the dashboard (prices, bios, loyalty rule).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets

from .db import DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE, name TEXT DEFAULT '', pin_hash TEXT, favourite TEXT DEFAULT '',
  createdAt TEXT, updatedAt TEXT
);
CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, kind TEXT, account_id INTEGER, createdAt TEXT);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, text TEXT, read INTEGER DEFAULT 0, createdAt TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_account ON notifications (account_id, id);
CREATE TABLE IF NOT EXISTS promos (
  code TEXT PRIMARY KEY, percent INTEGER, note TEXT DEFAULT '', active INTEGER DEFAULT 1, max_uses INTEGER DEFAULT 0,
  uses INTEGER DEFAULT 0, createdAt TEXT
);
CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, doctor_key TEXT DEFAULT '', kind TEXT DEFAULT 'work', file TEXT, caption TEXT DEFAULT '',
  createdAt TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def hash_pin(pin: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 120_000).hex()
    return salt + "$" + digest


def check_pin(pin: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt = stored.split("$", 1)[0]
    return hmac.compare_digest(hash_pin(pin, salt), stored)


class AppDB:
    def __init__(self, db: DB):
        self.db = db
        self.conn, self.lock = db.conn, db.lock
        self.conn.executescript(SCHEMA)

    def _rows(self, sql, args=()):
        return self.db._rows(sql, args)

    def _exec(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args)

    stamp = staticmethod(DB._stamp)

    # --- accounts ---------------------------------------------------------------
    def account_by_phone(self, phone):
        r = self._rows("SELECT * FROM accounts WHERE phone = ?", (phone,))
        return r[0] if r else None

    def account(self, account_id):
        r = self._rows("SELECT * FROM accounts WHERE id = ?", (int(account_id),))
        return r[0] if r else None

    def create_account(self, phone, name, pin) -> dict:
        ts = self.stamp()
        self._exec("INSERT INTO accounts (phone, name, pin_hash, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?)",
                   (phone, name, hash_pin(pin), ts, ts))
        return self.account_by_phone(phone)

    def update_account(self, account_id, **fields):
        fields = {k: v for k, v in fields.items() if k in ("name", "favourite", "pin_hash")}
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            self._exec(f"UPDATE accounts SET {sets}, updatedAt = ? WHERE id = ?", (*fields.values(), self.stamp(), int(account_id)))

    def count_accounts(self) -> int:
        return self._rows("SELECT COUNT(*) AS n FROM accounts")[0]["n"]

    # --- tokens -------------------------------------------------------------------
    def new_token(self, kind, account_id=0) -> str:
        tok = secrets.token_urlsafe(32)
        self._exec("INSERT INTO tokens (token, kind, account_id, createdAt) VALUES (?, ?, ?, ?)", (tok, kind, int(account_id), self.stamp()))
        return tok

    def token(self, tok):
        r = self._rows("SELECT * FROM tokens WHERE token = ?", (tok or "",))
        return r[0] if r else None

    def drop_token(self, tok):
        self._exec("DELETE FROM tokens WHERE token = ?", (tok or "",))

    # --- notifications ------------------------------------------------------------
    def notify(self, account_id, text):
        self._exec("INSERT INTO notifications (account_id, text, createdAt) VALUES (?, ?, ?)", (int(account_id), text, self.stamp()))

    def notifications(self, account_id, limit=50):
        return self._rows("SELECT * FROM notifications WHERE account_id = ? ORDER BY id DESC LIMIT ?", (int(account_id), limit))

    def mark_read(self, account_id):
        self._exec("UPDATE notifications SET read = 1 WHERE account_id = ?", (int(account_id),))

    # --- promo codes ----------------------------------------------------------------
    def promos(self):
        return self._rows("SELECT * FROM promos ORDER BY createdAt DESC")

    def promo(self, code):
        r = self._rows("SELECT * FROM promos WHERE code = ?", ((code or "").strip().upper(),))
        return r[0] if r else None

    def usable_promo(self, code):
        p = self.promo(code)
        if not p or not p["active"] or (p["max_uses"] and p["uses"] >= p["max_uses"]):
            return None
        return p

    def save_promo(self, code, percent, note="", max_uses=0, active=True):
        self._exec("INSERT INTO promos (code, percent, note, max_uses, active, createdAt) VALUES (?, ?, ?, ?, ?, ?) "
                   "ON CONFLICT(code) DO UPDATE SET percent = excluded.percent, note = excluded.note, max_uses = excluded.max_uses, "
                   "active = excluded.active", (code.strip().upper(), int(percent), note, int(max_uses), int(bool(active)), self.stamp()))

    def use_promo(self, code):
        self._exec("UPDATE promos SET uses = uses + 1 WHERE code = ?", ((code or "").strip().upper(),))

    def delete_promo(self, code):
        self._exec("DELETE FROM promos WHERE code = ?", ((code or "").strip().upper(),))

    # --- photos -------------------------------------------------------------------
    def photos(self, doctor_key=None):
        if doctor_key is None:
            return self._rows("SELECT * FROM photos ORDER BY id DESC")
        return self._rows("SELECT * FROM photos WHERE doctor_key = ? ORDER BY id DESC", (doctor_key,))

    def add_photo(self, doctor_key, kind, file, caption) -> int:
        cur = self._exec("INSERT INTO photos (doctor_key, kind, file, caption, createdAt) VALUES (?, ?, ?, ?, ?)",
                         (doctor_key or "", kind, file, caption, self.stamp()))
        return cur.lastrowid

    def photo(self, photo_id):
        r = self._rows("SELECT * FROM photos WHERE id = ?", (int(photo_id),))
        return r[0] if r else None

    def delete_photo(self, photo_id):
        self._exec("DELETE FROM photos WHERE id = ?", (int(photo_id),))

    # --- settings -------------------------------------------------------------------
    def get(self, key, default=None):
        r = self._rows("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(r[0]["value"]) if r else default

    def put(self, key, value):
        self._exec("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                   (key, json.dumps(value, ensure_ascii=False)))
