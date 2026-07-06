from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


CATALOG_COMPATIBILITY_COLUMNS: dict[str, dict[str, str]] = {
    "products": {
        "image_url": "TEXT",
        "container_type": "TEXT",
        "volume_liters": "REAL",
        "price_minor": "INTEGER",
        "currency": "TEXT DEFAULT 'RUB'",
        "stock_quantity": "REAL NOT NULL DEFAULT 0",
        "availability_status": "TEXT NOT NULL DEFAULT 'unavailable'",
        "source_store_href": "TEXT",
        "source_folder_href": "TEXT",
        "sync_state": "TEXT NOT NULL DEFAULT 'active'",
        "price_type_prices_json": "TEXT NOT NULL DEFAULT '{}'",
        "description": "TEXT",
        "alcohol_percent": "REAL",
    },
    "business_catalog_items": {
        "price_type_prices_json": "TEXT NOT NULL DEFAULT '{}'",
        "alcohol_percent": "REAL",
    },
}


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if not table_exists:
        return set()
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_compatibility_columns(conn: sqlite3.Connection) -> list[str]:
    """Backfill columns added to older migrations for already-deployed SQLite DBs."""
    added: list[str] = []
    for table, columns in CATALOG_COMPATIBILITY_COLUMNS.items():
        existing = _existing_columns(conn, table)
        if not existing:
            continue
        for column, definition in columns.items():
            if column in existing:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            existing.add(column)
            added.append(f"{table}.{column}")
    if added:
        conn.commit()
    return added


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
    ensure_compatibility_columns(conn)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.name
        if version in applied:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        conn.commit()
        applied_now.append(version)
    ensure_compatibility_columns(conn)
    return applied_now
