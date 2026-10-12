"""SQLite storage: patient sessions, booking requests and the waitlist.

Replaces the n8n data tables (patient sessions, booking requests, waitlist, user languages).
Doctors live in config/clinic.yaml instead of a table.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .timeutil import iso_utc, now_ms

SESSION_COLS = ["chat_id", "stage", "doctor_key", "doctor_name", "appointment_date", "selected_time", "slot_options",
                "request_id", "service", "patient_name", "full_name", "phone", "replace_request_id", "quick_rebook",
                "visit_reason", "updated_note"]
REQUEST_COLS = ["request_id", "chat_id", "patient_name", "patient_full_name", "patient_phone", "telegram_username",
                "doctor_key", "service", "slot_start", "slot_end", "slot_key", "status", "expires_at", "decided_by",
                "calendar_event_id", "replaces_request_id", "reminder_24h_sent", "reminder_2h_sent", "patient_confirmed",
                "rating", "rating_asked"]
WAITLIST_COLS = ["chat_id", "doctor_key", "doctor_name", "wanted_date", "patient_name", "status", "note"]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS sessions (
  {", ".join(c + " TEXT DEFAULT ''" for c in SESSION_COLS)},
  createdAt TEXT, updatedAt TEXT,
  PRIMARY KEY (chat_id)
);
CREATE TABLE IF NOT EXISTS requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT UNIQUE, chat_id TEXT, patient_name TEXT, patient_full_name TEXT, patient_phone TEXT,
  telegram_username TEXT, doctor_key TEXT, service TEXT, slot_start TEXT, slot_end TEXT, slot_key TEXT,
  status TEXT, expires_at TEXT, decided_by TEXT DEFAULT '', calendar_event_id TEXT DEFAULT '',
  replaces_request_id TEXT DEFAULT '', reminder_24h_sent INTEGER DEFAULT 0, reminder_2h_sent INTEGER DEFAULT 0,
  patient_confirmed TEXT DEFAULT '', rating INTEGER DEFAULT 0, rating_asked INTEGER DEFAULT 0,
  createdAt TEXT, updatedAt TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_doctor ON requests (doctor_key, slot_start);
CREATE INDEX IF NOT EXISTS idx_requests_chat ON requests (chat_id);
CREATE TABLE IF NOT EXISTS user_langs (
  chat_id TEXT PRIMARY KEY, lang TEXT DEFAULT '', createdAt TEXT, updatedAt TEXT
);
CREATE TABLE IF NOT EXISTS waitlist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  {", ".join(c + " TEXT DEFAULT ''" for c in WAITLIST_COLS)},
  createdAt TEXT, updatedAt TEXT
);
"""

BOOL_COLS = {"reminder_24h_sent", "reminder_2h_sent", "rating_asked"}


class DB:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True) if str(path) != ":memory:" else None
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.lock = threading.Lock()

    # --- helpers ---------------------------------------------------------------
    def _rows(self, sql, args=()):
        with self.lock:
            return [self._dict(r) for r in self.conn.execute(sql, args).fetchall()]

    @staticmethod
    def _dict(row) -> dict:
        d = dict(row)
        for c in BOOL_COLS:
            if c in d:
                d[c] = bool(d[c])
        return d

    @staticmethod
    def _stamp() -> str:
        return iso_utc(now_ms())

    # --- languages (n8n table clinic_user_langs) ------------------------------------
    def all_langs(self) -> dict:
        return {r["chat_id"]: r["lang"] for r in self._rows("SELECT chat_id, lang FROM user_langs") if r["chat_id"] and r["lang"]}

    def get_lang(self, chat_id) -> str:
        rows = self._rows("SELECT lang FROM user_langs WHERE chat_id = ?", (str(chat_id),))
        return (rows[0]["lang"] if rows else "") or "hy"

    def has_lang(self, chat_id) -> bool:
        return bool(self._rows("SELECT 1 FROM user_langs WHERE chat_id = ? AND lang != ''", (str(chat_id),)))

    def set_lang(self, chat_id, lang: str) -> None:
        ts = self._stamp()
        with self.lock:
            self.conn.execute("INSERT INTO user_langs (chat_id, lang, createdAt, updatedAt) VALUES (?, ?, ?, ?) "
                              "ON CONFLICT(chat_id) DO UPDATE SET lang = excluded.lang, updatedAt = excluded.updatedAt",
                              (str(chat_id), lang, ts, ts))

    # --- sessions --------------------------------------------------------------
    def get_session(self, chat_id) -> dict:
        rows = self._rows("SELECT * FROM sessions WHERE chat_id = ?", (str(chat_id),))
        return rows[0] if rows else {}

    def upsert_session(self, chat_id, **fields) -> None:
        fields = {k: ("" if v is None else str(v)) for k, v in fields.items() if k in SESSION_COLS and k != "chat_id"}
        cid, stamp = str(chat_id), self._stamp()
        with self.lock:
            exists = self.conn.execute("SELECT 1 FROM sessions WHERE chat_id = ?", (cid,)).fetchone()
            if exists:
                if fields:
                    sets = ", ".join(f"{k} = ?" for k in fields)
                    self.conn.execute(f"UPDATE sessions SET {sets}, updatedAt = ? WHERE chat_id = ?", (*fields.values(), stamp, cid))
            else:
                cols = ["chat_id", *fields.keys(), "createdAt", "updatedAt"]
                self.conn.execute(f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                  (cid, *fields.values(), stamp, stamp))

    def update_session_if(self, chat_id, request_id, **fields) -> None:
        """Update the session only if it still points at this request."""
        if self.get_session(chat_id).get("request_id") == request_id:
            self.upsert_session(chat_id, **fields)

    # --- booking requests ------------------------------------------------------
    def get_request(self, request_id) -> dict | None:
        rows = self._rows("SELECT * FROM requests WHERE request_id = ?", (request_id,))
        return rows[0] if rows else None

    def insert_request(self, row: dict) -> int:
        row = {k: v for k, v in row.items() if k in REQUEST_COLS}
        stamp = self._stamp()
        cols = [*row.keys(), "createdAt", "updatedAt"]
        with self.lock:
            cur = self.conn.execute(f"INSERT INTO requests ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                    (*row.values(), stamp, stamp))
            return cur.lastrowid

    def update_request(self, request_id, where_status: str | None = None, **fields) -> bool:
        """Conditional update (like the n8n 'status = X' filter). Returns True if a row changed —
        this is the lock that stops two people approving the same request."""
        fields = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items() if k in REQUEST_COLS}
        sets = ", ".join(f"{k} = ?" for k in fields)
        sql = f"UPDATE requests SET {sets}, updatedAt = ? WHERE request_id = ?"
        args = [*fields.values(), self._stamp(), request_id]
        if where_status is not None:
            sql += " AND status = ?"
            args.append(where_status)
        with self.lock:
            return self.conn.execute(sql, args).rowcount > 0

    def requests_for_doctor(self, doctor_key, day: str | None = None) -> list:
        if day:
            return self._rows("SELECT * FROM requests WHERE doctor_key = ? AND slot_start LIKE ? ORDER BY id", (doctor_key, day + "%"))
        return self._rows("SELECT * FROM requests WHERE doctor_key = ? ORDER BY id", (doctor_key,))

    def requests_for_chat(self, chat_id) -> list:
        return self._rows("SELECT * FROM requests WHERE chat_id = ? ORDER BY id", (str(chat_id),))

    def requests_by_status(self, status) -> list:
        return self._rows("SELECT * FROM requests WHERE status = ? ORDER BY id", (status,))

    def all_requests(self) -> list:
        return self._rows("SELECT * FROM requests ORDER BY id")

    # --- waitlist --------------------------------------------------------------
    def upsert_waitlist(self, chat_id, doctor_key, **fields) -> None:
        fields = {k: ("" if v is None else str(v)) for k, v in fields.items() if k in WAITLIST_COLS}
        cid, stamp = str(chat_id), self._stamp()
        with self.lock:
            row = self.conn.execute("SELECT id FROM waitlist WHERE chat_id = ? AND doctor_key = ?", (cid, doctor_key)).fetchone()
            if row:
                sets = ", ".join(f"{k} = ?" for k in fields)
                self.conn.execute(f"UPDATE waitlist SET {sets}, updatedAt = ? WHERE id = ?", (*fields.values(), stamp, row["id"]))
            else:
                cols = ["chat_id", "doctor_key", *fields.keys(), "createdAt", "updatedAt"]
                self.conn.execute(f"INSERT INTO waitlist ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                  (cid, doctor_key, *fields.values(), stamp, stamp))

    def waiting_for_doctor(self, doctor_key) -> list:
        return self._rows("SELECT * FROM waitlist WHERE doctor_key = ? AND status = 'waiting' ORDER BY id", (doctor_key,))

    def mark_waitlist(self, chat_id, doctor_key, status, note="") -> None:
        with self.lock:
            self.conn.execute("UPDATE waitlist SET status = ?, note = ?, updatedAt = ? WHERE chat_id = ? AND doctor_key = ? AND status = 'waiting'",
                              (status, note, self._stamp(), str(chat_id), doctor_key))
