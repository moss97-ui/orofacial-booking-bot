"""Settings from environment variables (or a .env file). Secrets never live in the code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    telegram_token: str
    clinic_config: str
    database_path: str
    google_service_account_file: str
    webhook_url: str
    webhook_secret: str
    port: int
    reminder_interval_minutes: int
    log_level: str


def load_settings() -> Settings:
    _load_dotenv(Path(os.environ.get("ENV_FILE", ".env")))
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")
    return Settings(
        telegram_token=token,
        clinic_config=os.environ.get("CLINIC_CONFIG", "config/clinic.yaml"),
        database_path=os.environ.get("DATABASE_PATH", "data/bot.sqlite3"),
        google_service_account_file=os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", ""),
        webhook_url=os.environ.get("WEBHOOK_URL", ""),
        webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
        port=int(os.environ.get("PORT", "8080")),
        reminder_interval_minutes=int(os.environ.get("REMINDER_INTERVAL_MINUTES", "30")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
