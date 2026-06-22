from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    ensure_migrations_table(conn)
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def run_migrations(conn: sqlite3.Connection) -> list[str]:
    ensure_migrations_table(conn)
    applied = applied_versions(conn)
    applied_now: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.name
        if version in applied:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        conn.commit()
        applied_now.append(version)
    return applied_now
