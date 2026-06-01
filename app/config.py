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
        admin_email=os.getenv("ADMIN_EMAIL", "admin@stamm.local"),
        admin_password=os.getenv("ADMIN_PASSWORD", "stamm-admin"),
        moysklad_api_base_url=os.getenv(
            "MOYSKLAD_API_BASE_URL",
            "https://api.moysklad.ru/api/remap/1.2",
        ),
    )
