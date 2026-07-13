from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.db.connection import connect
from app.db.migrations import run_migrations
from app.db.seed import seed_core
from app.integrations.moysklad.catalog_sync import run_manual_catalog_sync, utc_now_iso
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


STALE_RUNNING_AFTER_MINUTES = 180
STALE_RUNNING_ERROR = "Автосинхронизация была прервана: сайт был остановлен или процесс синхронизации завершился без финального статуса."


def recover_stale_auto_sync_jobs(conn: sqlite3.Connection, *, stale_after_minutes: int = STALE_RUNNING_AFTER_MINUTES) -> int:
    """Mark interrupted auto-sync jobs as failed so they do not block future runs forever."""
    cutoff = _now() - timedelta(minutes=max(5, int(stale_after_minutes or STALE_RUNNING_AFTER_MINUTES)))
    stale_ids: list[int] = []
    rows = conn.execute(
        """
        SELECT id, started_at, created_at
        FROM moysklad_sync_jobs
        WHERE trigger_source = 'auto' AND status = 'running'
        """
    ).fetchall()
    for row in rows:
        started_at = _parse_iso(row["started_at"]) or _parse_iso(row["created_at"])
        if started_at is None or started_at <= cutoff:
            stale_ids.append(int(row["id"]))
    if not stale_ids:
        return 0
    finished = utc_now_iso()
    placeholders = ",".join("?" for _ in stale_ids)
    conn.execute(
        f"""
        UPDATE moysklad_sync_jobs
        SET status = 'failed', finished_at = ?, error_summary = ?
        WHERE id IN ({placeholders})
        """,
        (finished, STALE_RUNNING_ERROR, *stale_ids),
    )
    conn.execute(
        """
        UPDATE moysklad_sync_settings
        SET last_error_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (finished,),
    )
    for job_id in stale_ids:
        conn.execute(
            """
            INSERT INTO moysklad_sync_logs (job_id, level, stage, message, error_code)
            VALUES (?, 'error', 'auto_sync_recovery', ?, 'AUTO_SYNC_INTERRUPTED')
            """,
            (job_id, STALE_RUNNING_ERROR),
        )
    conn.commit()
    return len(stale_ids)


def compact_auto_sync_history(conn: sqlite3.Connection, limit: int = 3) -> list[dict[str, Any]]:
    recover_stale_auto_sync_jobs(conn)
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
    recovered_stale_jobs = recover_stale_auto_sync_jobs(conn)
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
        "recoveredStaleJobs": recovered_stale_jobs,
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
                    # The failed job is recorded by run_manual_catalog_sync when possible.
                    # If the exception happened before/around DB writes, keep the worker alive
                    # and clear the connection transaction so later polls can recover.
                    try:
                        conn.rollback()
                    except sqlite3.Error:
                        pass
                time.sleep(max(5, poll_seconds))
        finally:
            if conn is not None:
                conn.close()

    thread = threading.Thread(target=loop, name="moysklad-auto-sync", daemon=True)
    thread.start()
    return thread
