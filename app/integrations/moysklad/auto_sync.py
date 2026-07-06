from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.connection import connect
from app.db.migrations import run_migrations
from app.db.seed import seed_core
from app.integrations.moysklad.catalog_sync import run_manual_catalog_sync
from app.integrations.moysklad.settings_service import get_settings


def _parse_iso(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def compact_auto_sync_history(conn: sqlite3.Connection, limit: int = 3) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, status, started_at, finished_at, error_summary
        FROM moysklad_sync_jobs
        WHERE trigger_source = 'auto'
        ORDER BY coalesce(started_at, created_at) DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "status": row["status"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "error": row["error_summary"],
        }
        for row in rows
    ]


def auto_sync_status(conn: sqlite3.Connection) -> dict[str, Any]:
    settings = get_settings(conn)
    last = conn.execute(
        """
        SELECT * FROM moysklad_sync_jobs
        WHERE trigger_source = 'auto'
        ORDER BY coalesce(started_at, created_at) DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    interval = max(15, int(settings["full_sync_interval_minutes"] or 360))
    enabled = bool(settings["is_enabled"])
    running = conn.execute(
        "SELECT 1 FROM moysklad_sync_jobs WHERE trigger_source = 'auto' AND status = 'running' LIMIT 1"
    ).fetchone() is not None
    last_started = _parse_iso(last["started_at"] if last else None)
    due = bool(enabled and settings["encrypted_token"] and settings["source_product_folder_href"] and settings["store_href"] and not running)
    if due and last_started is not None:
        due = (_now() - last_started).total_seconds() >= interval * 60
    return {
        "enabled": enabled,
        "configured": bool(settings["encrypted_token"] and settings["source_product_folder_href"] and settings["store_href"]),
        "running": running,
        "intervalMinutes": interval,
        "due": due,
        "lastRunAt": last["started_at"] if last else None,
        "history": compact_auto_sync_history(conn),
    }


def run_auto_catalog_sync_if_due(conn: sqlite3.Connection) -> dict[str, Any]:
    status = auto_sync_status(conn)
    if not status["due"]:
        return {"status": "skipped", "reason": "not_due", "autoSync": status}
    return run_manual_catalog_sync(conn, None, diagnostic_mode=False, trigger_source="auto", job_type="auto_catalog")


def start_auto_sync_worker(database_path: Path | str, admin_email: str, admin_password: str, *, poll_seconds: int = 60) -> threading.Thread:
    def loop() -> None:
        conn: sqlite3.Connection | None = None
        try:
            conn = connect(database_path)
            run_migrations(conn)
            seed_core(conn, admin_email, admin_password)
            while True:
                try:
                    run_auto_catalog_sync_if_due(conn)
                except Exception:
                    # The failed job is recorded by run_manual_catalog_sync; keep worker alive.
                    pass
                time.sleep(max(5, poll_seconds))
        finally:
            if conn is not None:
                conn.close()

    thread = threading.Thread(target=loop, name="moysklad-auto-sync", daemon=True)
    thread.start()
    return thread
