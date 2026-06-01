from __future__ import annotations

import sqlite3
from app.modules.auth.security import hash_password

PERMISSIONS = [
    "content.read", "content.write", "content.publish",
    "catalog.read", "catalog.write_overrides", "catalog.publish",
    "moysklad.read", "moysklad.write_settings", "moysklad.run_sync",
    "orders.read", "orders.write_status", "orders.export",
    "users.read", "users.write", "audit.read",
]

ROLES = {
    "admin": "Полный доступ",
    "content_manager": "Контент и SEO",
    "catalog_manager": "Каталог и витринные override-поля",
    "integration_manager": "Настройки и синхронизация МойСклад",
    "sales_manager": "B2B-заявки",
    "viewer": "Только чтение",
}


def seed_core(conn: sqlite3.Connection, admin_email: str, admin_password: str) -> None:
    for code in PERMISSIONS:
        conn.execute(
            "INSERT OR IGNORE INTO permissions (code, description) VALUES (?, ?)",
            (code, code),
        )
    for code, name in ROLES.items():
        conn.execute(
            "INSERT OR IGNORE INTO roles (code, name, description) VALUES (?, ?, ?)",
            (code, name, name),
        )
    admin_role_id = conn.execute("SELECT id FROM roles WHERE code = 'admin'").fetchone()[0]
    for permission_id, in conn.execute("SELECT id FROM permissions"):
        conn.execute(
            "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
            (admin_role_id, permission_id),
        )
    password_hash = hash_password(admin_password)
    conn.execute(
        """
        INSERT OR IGNORE INTO users (email, name, password_hash, status)
        VALUES (?, ?, ?, 'active')
        """,
        (admin_email, "Stamm Admin", password_hash),
    )
    user_id = conn.execute("SELECT id FROM users WHERE email = ?", (admin_email,)).fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
        (user_id, admin_role_id),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO moysklad_sync_settings (
            id, api_base_url, include_child_folders, full_sync_interval_minutes,
            stock_sync_interval_minutes, is_enabled
        ) VALUES (1, 'https://api.moysklad.ru/api/remap/1.2', 1, 360, 120, 0)
        """
    )
    conn.commit()
