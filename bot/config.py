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
    i18n_file: str
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
    clinic_config = os.environ.get("CLINIC_CONFIG", "config/clinic.yaml")
    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    # Hosts without files (Railway, Render, Heroku…): the clinic YAML and the Google key can be pasted into variables.
    runtime = Path(os.environ.get("RUNTIME_DIR", "/tmp/clinic-bot"))
    if os.environ.get("CLINIC_CONFIG_YAML", "").strip():
        runtime.mkdir(parents=True, exist_ok=True)
        clinic_config = str(runtime / "clinic.yaml")
        Path(clinic_config).write_text(os.environ["CLINIC_CONFIG_YAML"], encoding="utf-8")
    if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip():
        runtime.mkdir(parents=True, exist_ok=True)
        sa_file = str(runtime / "google-service-account.json")
        Path(sa_file).write_text(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"], encoding="utf-8")
        os.chmod(sa_file, 0o600)
    return Settings(
        telegram_token=token,
        clinic_config=clinic_config,
        database_path=os.environ.get("DATABASE_PATH", "data/bot.sqlite3"),
        google_service_account_file=sa_file,
        i18n_file=os.environ.get("I18N_FILE", "n8n/clinic-i18n.json"),
        webhook_url=os.environ.get("WEBHOOK_URL", ""),
        webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
        port=int(os.environ.get("PORT", "8080")),
        reminder_interval_minutes=int(os.environ.get("REMINDER_INTERVAL_MINUTES", "30")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
