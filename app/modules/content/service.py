from __future__ import annotations

import sqlite3
from typing import Any

HOME_DEFAULTS = {
    "home_hero_title": "STAMM",
    "home_hero_subtitle": "BREWING",
    "home_logo_url": "",
}

MENU_DEFAULTS = [
    {"key": "beer", "href": "/beer", "label": "Пиво", "sort_order": 10, "is_visible": True},
    {"key": "visit", "href": "/visit", "label": "Посетить пивоварню", "sort_order": 20, "is_visible": True},
    {"key": "history", "href": "/history", "label": "История", "sort_order": 30, "is_visible": True},
    {"key": "business", "href": "/business", "label": "Бизнес", "sort_order": 40, "is_visible": True},
    {"key": "contacts", "href": "/contacts", "label": "Контакты", "sort_order": 50, "is_visible": True},
]

ACTION_DEFAULTS = [
    {"key": "tg", "label": "TG", "href": "https://t.me/", "sort_order": 10, "is_visible": True},
    {"key": "vk", "label": "VK", "href": "https://vk.com/", "sort_order": 20, "is_visible": True},
    {"key": "untappd", "label": "Untappd", "href": "https://untappd.com/", "sort_order": 30, "is_visible": True},
    {"key": "cart", "label": "Корзина", "href": "/business#cart", "sort_order": 40, "is_visible": True},
    {"key": "account", "label": "Личный кабинет", "href": "/account", "sort_order": 50, "is_visible": True},
]


def ensure_public_content_defaults(conn: sqlite3.Connection) -> None:
    for key, value in HOME_DEFAULTS.items():
        conn.execute("INSERT OR IGNORE INTO site_content_settings (key, value) VALUES (?, ?)", (key, value))
    for item in MENU_DEFAULTS:
        conn.execute(
            """
            INSERT OR IGNORE INTO public_menu_items (key, href, label, sort_order, is_visible)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item["key"], item["href"], item["label"], item["sort_order"], 1 if item["is_visible"] else 0),
        )
    for item in ACTION_DEFAULTS:
        conn.execute(
            """
            INSERT OR IGNORE INTO public_nav_actions (key, label, href, sort_order, is_visible)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item["key"], item["label"], item["href"], item["sort_order"], 1 if item["is_visible"] else 0),
        )
    conn.commit()


def get_public_site_content(conn: sqlite3.Connection, include_hidden: bool = False) -> dict[str, Any]:
    ensure_public_content_defaults(conn)
    settings = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM site_content_settings").fetchall()}
    visibility_clause = "" if include_hidden else "WHERE is_visible = 1"
    menu = [
        dict(row)
        for row in conn.execute(
            f"SELECT key, href, label, sort_order, is_visible FROM public_menu_items {visibility_clause} ORDER BY sort_order ASC, key ASC"
        ).fetchall()
    ]
    actions = [
        dict(row)
        for row in conn.execute(
            f"SELECT key, label, href, sort_order, is_visible FROM public_nav_actions {visibility_clause} ORDER BY sort_order ASC, key ASC"
        ).fetchall()
    ]
    return {"home": {**HOME_DEFAULTS, **settings}, "menu": menu, "actions": actions}


def save_public_content(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    for key in HOME_DEFAULTS:
        if key in data:
            conn.execute(
                """
                INSERT INTO site_content_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, str(data.get(key) or "")),
            )
    for item in MENU_DEFAULTS:
        key = item["key"]
        conn.execute(
            """
            UPDATE public_menu_items
            SET label = ?, sort_order = ?, is_visible = ?, updated_at = CURRENT_TIMESTAMP
            WHERE key = ?
            """,
            (
                str(data.get(f"menu_{key}_label") or item["label"]),
                int(data.get(f"menu_{key}_sort_order") or item["sort_order"]),
                1 if data.get(f"menu_{key}_visible") else 0,
                key,
            ),
        )
    for item in ACTION_DEFAULTS:
        key = item["key"]
        conn.execute(
            """
            UPDATE public_nav_actions
            SET label = ?, href = ?, sort_order = ?, is_visible = ?, updated_at = CURRENT_TIMESTAMP
            WHERE key = ?
            """,
            (
                str(data.get(f"action_{key}_label") or item["label"]),
                str(data.get(f"action_{key}_href") or item["href"]),
                int(data.get(f"action_{key}_sort_order") or item["sort_order"]),
                1 if data.get(f"action_{key}_visible") else 0,
                key,
            ),
        )
    conn.commit()
