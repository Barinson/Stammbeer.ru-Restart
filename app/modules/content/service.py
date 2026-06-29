from __future__ import annotations

import json
import sqlite3
from typing import Any

HOME_DEFAULTS = {
    "home_hero_title": "STAMM",
    "home_hero_subtitle": "BREWING",
    "home_logo_url": "",
    "home_hero_title_size_px": "152",
    "home_hero_title_weight": "950",
    "home_hero_subtitle_size_px": "112",
    "home_hero_subtitle_weight": "950",
    "home_hero_line_gap_px": "0",
    "home_content_bg_url": "",
    "home_news_title": "Готовим новую B2B-витрину Stamm Brewing",
    "home_news_text": "Готовим обновлённый сайт пивоварни: с чистой навигацией, B2B-витриной и фирменной подачей Stamm Brewing.",
    "home_news_image_url": "",
    "home_news_link_url": "/business",
    "home_news_link_label": "Перейти в B2B-каталог",
}

CONTACT_DEFAULTS = {
    "contacts_emails_json": '[{"label":"Основной","value":"info@stammbeer.ru","sort_order":10,"is_visible":true},{"label":"Заказы","value":"order@stammbeer.ru","sort_order":20,"is_visible":true}]',
    "contacts_phones_json": '[{"label":"Офис","value":"+7 (000) 000-00-00","sort_order":10,"is_visible":true},{"label":"Отдел продаж","value":"+7 (000) 000-00-01","sort_order":20,"is_visible":true}]',
    "contacts_address": "Адрес завода Stamm Brewing",
    "contacts_address_is_visible": "1",
    "contacts_address_color": "",
    "contacts_description": "Свяжитесь с нами по вопросам заказов, сотрудничества и визитов на производство.",
    "contacts_description_is_visible": "1",
    "contacts_description_color": "",
    "contacts_map_lat": "55.7558",
    "contacts_map_lng": "37.6173",
    "contacts_map_zoom": "13",
    "contacts_map_height_px": "240",
    "contacts_map_width_px": "420",
    "contacts_map_title": "Stamm Brewing",
}

TYPOGRAPHY_DEFAULTS = {
    "typography_nav_font_size_px": "14",
    "typography_page_title_font_size_px": "42",
    "typography_lead_font_size_px": "18",
    "typography_section_title_font_size_px": "26",
    "typography_body_font_size_px": "16",
    "typography_label_font_size_px": "13",
    "typography_product_title_font_size_px": "16",
    "typography_price_font_size_px": "17",
    "typography_cart_font_size_px": "14",
    "typography_contact_text_font_size_px": "18",
}

BUSINESS_DEFAULTS = {
    "business_min_order_amount_minor": "1500000",
}

LAYOUT_DEFAULTS = {
    "menu_offset_home_px": "176",
    "menu_offset_beer_px": "176",
    "menu_offset_visit_px": "176",
    "menu_offset_history_px": "176",
    "menu_offset_business_px": "176",
    "menu_offset_contacts_px": "176",
}

BEER_DEFAULTS = {
    "beer_partners_title": "Где найти Stamm Brewing",
    "beer_partners_description": "Партнёры, бары и магазины, где представлена наша продукция.",
    "beer_partners_is_visible": "1",
    "beer_partners_json": "[]",
    "beer_products_title": "Наша продукция",
    "beer_new_title": "Новинки",
    "beer_core_title": "Постоянная линейка",
    "beer_seasonal_title": "Сезонные сорта",
    "beer_products_is_visible": "1",
    "beer_new_is_visible": "1",
    "beer_core_is_visible": "1",
    "beer_seasonal_is_visible": "1",
    "beer_untappd_logo_url": "",
    "beer_popup_backdrop_color": "#0b3f40",
    "beer_popup_backdrop_opacity": "30",
    "beer_popup_card_color": "#0d4b4c",
    "beer_popup_card_opacity": "100",
    "beer_products_json": "[]",
}

MENU_DEFAULTS = [
    {"key": "beer", "href": "/beer", "label": "Пиво", "sort_order": 10, "is_visible": True},
    {"key": "visit", "href": "/visit", "label": "Посетить пивоварню", "sort_order": 20, "is_visible": True},
    {"key": "history", "href": "/history", "label": "История", "sort_order": 30, "is_visible": True},
    {"key": "business", "href": "/business", "label": "Бизнес", "sort_order": 40, "is_visible": True},
    {"key": "contacts", "href": "/contacts", "label": "Контакты", "sort_order": 50, "is_visible": True},
]

ACTION_DEFAULTS = [
    {"key": "tg", "label": "TG", "href": "https://t.me/", "icon_url": "", "sort_order": 10, "is_visible": True},
    {"key": "vk", "label": "VK", "href": "https://vk.com/", "icon_url": "", "sort_order": 20, "is_visible": True},
    {"key": "untappd", "label": "Untappd", "href": "https://untappd.com/", "icon_url": "", "sort_order": 30, "is_visible": True},
    {"key": "cart", "label": "Корзина", "href": "/business#cart", "icon_url": "", "sort_order": 40, "is_visible": True},
    {"key": "account", "label": "Личный кабинет", "href": "/account", "icon_url": "", "sort_order": 50, "is_visible": True},
]


def ensure_public_content_defaults(conn: sqlite3.Connection) -> None:
    for key, value in HOME_DEFAULTS.items():
        conn.execute("INSERT OR IGNORE INTO site_content_settings (key, value) VALUES (?, ?)", (key, value))
    for key, value in CONTACT_DEFAULTS.items():
        conn.execute("INSERT OR IGNORE INTO site_content_settings (key, value) VALUES (?, ?)", (key, value))
    for key, value in TYPOGRAPHY_DEFAULTS.items():
        conn.execute("INSERT OR IGNORE INTO site_content_settings (key, value) VALUES (?, ?)", (key, value))
    for key, value in BUSINESS_DEFAULTS.items():
        conn.execute("INSERT OR IGNORE INTO site_content_settings (key, value) VALUES (?, ?)", (key, value))
    for key, value in LAYOUT_DEFAULTS.items():
        conn.execute("INSERT OR IGNORE INTO site_content_settings (key, value) VALUES (?, ?)", (key, value))
    for key, value in BEER_DEFAULTS.items():
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
            INSERT OR IGNORE INTO public_nav_actions (key, label, href, icon_url, sort_order, is_visible)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (item["key"], item["label"], item["href"], item["icon_url"], item["sort_order"], 1 if item["is_visible"] else 0),
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
            f"SELECT key, label, href, icon_url, sort_order, is_visible FROM public_nav_actions {visibility_clause} ORDER BY sort_order ASC, key ASC"
        ).fetchall()
    ]
    contacts = {**CONTACT_DEFAULTS, **settings}
    for key in ("contacts_emails_json", "contacts_phones_json"):
        target = key.removeprefix("contacts_").removesuffix("_json")
        try:
            items = json.loads(str(contacts.get(key) or "[]"))
        except json.JSONDecodeError:
            items = []
        normalized_items = []
        for index, item in enumerate(items if isinstance(items, list) else []):
            if not isinstance(item, dict):
                continue
            normalized_items.append({
                "label": str(item.get("label") or ""),
                "value": str(item.get("value") or ""),
                "sort_order": int(item.get("sort_order") or ((index + 1) * 10)),
                "is_visible": bool(item.get("is_visible", True)),
            })
        contacts[target] = sorted(normalized_items, key=lambda item: (item["sort_order"], item["label"]))
    beer = {**BEER_DEFAULTS, **settings}
    for key in ("beer_partners_json", "beer_products_json"):
        try:
            items = json.loads(str(beer.get(key) or "[]"))
        except json.JSONDecodeError:
            items = []
        beer[key.removeprefix("beer_").removesuffix("_json")] = sorted(
            [item for item in items if isinstance(item, dict)],
            key=lambda item: (int(item.get("sort_order") or 100), str(item.get("name") or "")),
        )
    return {
        "home": {**HOME_DEFAULTS, **settings},
        "contacts": contacts,
        "typography": {**TYPOGRAPHY_DEFAULTS, **settings},
        "business": {**BUSINESS_DEFAULTS, **settings},
        "layout": {**LAYOUT_DEFAULTS, **settings},
        "beer": beer,
        "menu": menu,
        "actions": actions,
    }


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
    for key in TYPOGRAPHY_DEFAULTS:
        if key in data:
            conn.execute(
                """
                INSERT INTO site_content_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, str(data.get(key) or TYPOGRAPHY_DEFAULTS[key])),
            )
    if any(key.startswith("contact_") or key.startswith("contacts_") for key in data):
        contact_emails = []
        contact_phones = []
        for index in range(8):
            email_value = str(data.get(f"contact_email_value_{index}") or "").strip()
            email_label = str(data.get(f"contact_email_label_{index}") or "").strip()
            if email_value:
                contact_emails.append({
                    "label": email_label or "E-mail",
                    "value": email_value,
                    "sort_order": int(data.get(f"contact_email_sort_order_{index}") or ((index + 1) * 10)),
                    "is_visible": bool(data.get(f"contact_email_visible_{index}")),
                })
            phone_value = str(data.get(f"contact_phone_value_{index}") or "").strip()
            phone_label = str(data.get(f"contact_phone_label_{index}") or "").strip()
            if phone_value:
                contact_phones.append({
                    "label": phone_label or "Телефон",
                    "value": phone_value,
                    "sort_order": int(data.get(f"contact_phone_sort_order_{index}") or ((index + 1) * 10)),
                    "is_visible": bool(data.get(f"contact_phone_visible_{index}")),
                })
        contact_values = {
            "contacts_emails_json": json.dumps(contact_emails, ensure_ascii=False),
            "contacts_phones_json": json.dumps(contact_phones, ensure_ascii=False),
        }
        for key in ("contacts_address", "contacts_address_color", "contacts_description", "contacts_description_color", "contacts_map_lat", "contacts_map_lng", "contacts_map_zoom", "contacts_map_height_px", "contacts_map_width_px", "contacts_map_title"):
            if key in data:
                contact_values[key] = str(data.get(key) or "")
        contact_values["contacts_address_is_visible"] = "1" if str(data.get("contacts_address_is_visible", "1")).strip().lower() not in {"0", "false", "off", "no"} else "0"
        contact_values["contacts_description_is_visible"] = "1" if str(data.get("contacts_description_is_visible", "1")).strip().lower() not in {"0", "false", "off", "no"} else "0"
        for key, value in contact_values.items():
            conn.execute(
                """
                INSERT INTO site_content_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
            )
    for key in BUSINESS_DEFAULTS:
        if key in data:
            conn.execute(
                """
                INSERT INTO site_content_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, str(data.get(key) or "")),
            )
    for key in LAYOUT_DEFAULTS:
        if key in data:
            conn.execute(
                """
                INSERT INTO site_content_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, str(data.get(key) or LAYOUT_DEFAULTS[key])),
            )
    if any(key.startswith("beer_") for key in data):
        beer_values = {
            "beer_partners_title": str(data.get("beer_partners_title") or BEER_DEFAULTS["beer_partners_title"]),
            "beer_partners_description": str(data.get("beer_partners_description") or ""),
            "beer_partners_is_visible": "1" if str(data.get("beer_partners_is_visible", "1")).lower() not in {"0", "false", "off", "no"} else "0",
            "beer_products_title": str(data.get("beer_products_title") or BEER_DEFAULTS["beer_products_title"]),
            "beer_new_title": str(data.get("beer_new_title") or BEER_DEFAULTS["beer_new_title"]),
            "beer_core_title": str(data.get("beer_core_title") or BEER_DEFAULTS["beer_core_title"]),
            "beer_seasonal_title": str(data.get("beer_seasonal_title") or BEER_DEFAULTS["beer_seasonal_title"]),
            "beer_products_is_visible": "1" if str(data.get("beer_products_is_visible", "1")).lower() not in {"0", "false", "off", "no"} else "0",
            "beer_new_is_visible": "1" if str(data.get("beer_new_is_visible", "1")).lower() not in {"0", "false", "off", "no"} else "0",
            "beer_core_is_visible": "1" if str(data.get("beer_core_is_visible", "1")).lower() not in {"0", "false", "off", "no"} else "0",
            "beer_seasonal_is_visible": "1" if str(data.get("beer_seasonal_is_visible", "1")).lower() not in {"0", "false", "off", "no"} else "0",
            "beer_untappd_logo_url": str(data.get("beer_untappd_logo_url") or ""),
            "beer_popup_backdrop_color": str(data.get("beer_popup_backdrop_color") or BEER_DEFAULTS["beer_popup_backdrop_color"]),
            "beer_popup_backdrop_opacity": str(data.get("beer_popup_backdrop_opacity") or BEER_DEFAULTS["beer_popup_backdrop_opacity"]),
            "beer_popup_card_color": str(data.get("beer_popup_card_color") or BEER_DEFAULTS["beer_popup_card_color"]),
            "beer_popup_card_opacity": str(data.get("beer_popup_card_opacity") or BEER_DEFAULTS["beer_popup_card_opacity"]),
        }
        partners = []
        partner_indices = sorted({int(key.rsplit("_", 1)[1]) for key in data if key.startswith("beer_partner_name_") and key.rsplit("_", 1)[1].isdigit()} | {int(key.rsplit("_", 1)[1]) for key in data if key.startswith("beer_partner_logo_url_") and key.rsplit("_", 1)[1].isdigit()})
        for index in partner_indices:
            name = str(data.get(f"beer_partner_name_{index}") or "").strip()
            logo = str(data.get(f"beer_partner_logo_url_{index}") or "").strip()
            if name or logo:
                partners.append({
                    "name": name, "logo_url": logo, "url": str(data.get(f"beer_partner_url_{index}") or "").strip(),
                    "size": str(data.get(f"beer_partner_size_{index}") or "medium"),
                    "sort_order": int(data.get(f"beer_partner_sort_order_{index}") or ((index + 1) * 10)),
                    "is_visible": str(data.get(f"beer_partner_visible_{index}", "1")).lower() not in {"0", "false", "off", "no"},
                })
        products = []
        product_indices = sorted({int(key.rsplit("_", 1)[1]) for key in data if key.startswith("beer_product_name_") and key.rsplit("_", 1)[1].isdigit()} | {int(key.rsplit("_", 1)[1]) for key in data if key.startswith("beer_product_image_url_") and key.rsplit("_", 1)[1].isdigit()})
        for index in product_indices:
            if str(data.get(f"beer_product_delete_{index}") or "").strip() == "1":
                continue
            name = str(data.get(f"beer_product_name_{index}") or "").strip()
            image = str(data.get(f"beer_product_image_url_{index}") or "").strip()
            if name or image:
                products.append({
                    "name": name, "style": str(data.get(f"beer_product_style_{index}") or "").strip(),
                    "abv": str(data.get(f"beer_product_abv_{index}") or "").strip(),
                    "image_url": image, "untappd_url": str(data.get(f"beer_product_untappd_url_{index}") or "").strip(),
                    "category": str(data.get(f"beer_product_category_{index}") or "seasonal"),
                    "sort_order": int(data.get(f"beer_product_sort_order_{index}") or ((index + 1) * 10)),
                    "is_visible": str(data.get(f"beer_product_visible_{index}", "1")).lower() not in {"0", "false", "off", "no"},
                })
        beer_values["beer_partners_json"] = json.dumps(partners, ensure_ascii=False)
        beer_values["beer_products_json"] = json.dumps(products, ensure_ascii=False)
        for key, value in beer_values.items():
            conn.execute(
                """
                INSERT INTO site_content_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (key, value),
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
            SET label = ?, href = ?, icon_url = ?, sort_order = ?, is_visible = ?, updated_at = CURRENT_TIMESTAMP
            WHERE key = ?
            """,
            (
                str(data.get(f"action_{key}_label") or item["label"]),
                str(data.get(f"action_{key}_href") or item["href"]),
                str(data.get(f"action_{key}_icon_url") or item["icon_url"]),
                int(data.get(f"action_{key}_sort_order") or item["sort_order"]),
                1 if data.get(f"action_{key}_visible") else 0,
                key,
            ),
        )
    conn.commit()
