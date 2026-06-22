from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    env: str
    host: str
    port: int
    database_url: str
    session_secret: str
    admin_email: str
    admin_password: str
    moysklad_api_base_url: str
    public_base_url: str = "http://127.0.0.1:8000"
    email_provider: str = "yandex"
    email_enabled: bool = False
    email_smtp_host: str = "smtp.yandex.com"
    email_smtp_port: int = 465
    email_smtp_username: str = ""
    email_smtp_password: str = ""
    email_from_email: str = ""
    email_from_name: str = "Stamm Brewing"

    @property
    def sqlite_path(self) -> Path:
        if self.database_url.startswith("sqlite:///"):
            return Path(self.database_url.replace("sqlite:///", "", 1))
        return Path(self.database_url)


def load_settings() -> Settings:
    env = os.getenv("APP_ENV", "development")
    default_db = "sqlite:///var/stamm.sqlite3"
    return Settings(
        app_name="Stamm Brewing Core",
        env=env,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        database_url=os.getenv("DATABASE_URL", default_db),
        session_secret=os.getenv("SESSION_SECRET", "dev-session-secret-change-me"),
        admin_email=os.getenv("ADMIN_EMAIL", "admin"),
        admin_password=os.getenv("ADMIN_PASSWORD", "1"),
        moysklad_api_base_url=os.getenv(
            "MOYSKLAD_API_BASE_URL",
            "https://api.moysklad.ru/api/remap/1.2",
        ),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        email_provider=os.getenv("EMAIL_PROVIDER", "yandex"),
        email_enabled=os.getenv("EMAIL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        email_smtp_host=os.getenv("EMAIL_SMTP_HOST", "smtp.yandex.com"),
        email_smtp_port=int(os.getenv("EMAIL_SMTP_PORT", "465")),
        email_smtp_username=os.getenv("EMAIL_SMTP_USERNAME", ""),
        email_smtp_password=os.getenv("EMAIL_SMTP_PASSWORD", ""),
        email_from_email=os.getenv("EMAIL_FROM_EMAIL", os.getenv("EMAIL_SMTP_USERNAME", "")),
        email_from_name=os.getenv("EMAIL_FROM_NAME", "Stamm Brewing"),
    )
