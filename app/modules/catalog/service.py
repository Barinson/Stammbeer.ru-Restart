from __future__ import annotations

import sqlite3
from typing import Any

CONTAINER_LABELS = {
    "keg": "Кеги",
    "can": "Банки",
    "bottle": "Бутылки",
}

AVAILABILITY_LABELS = {
    "available": "В наличии",
    "limited": "Мало",
    "preorder": "Предзаказ",
    "unavailable": "Нет в наличии",
    "hidden": "Скрыто",
}

PUBLIC_FILTERS = {"all", "keg", "can"}


def normalize_container_filter(value: str | None) -> str:
    if not value:
        return "all"
    value = value.strip().lower()
    return value if value in PUBLIC_FILTERS else "all"


def _price_payload(price_minor: int | None, currency: str | None) -> dict[str, Any]:
    if price_minor is None:
        return {"visibility": "hidden", "label": "Цена по запросу"}
    return {
        "visibility": "public",
        "amountMinor": price_minor,
        "currency": currency or "RUB",
        "label": f"{price_minor / 100:,.0f} ₽".replace(",", " "),
    }


def public_catalog(conn: sqlite3.Connection, container_type: str | None = None) -> dict[str, Any]:
    selected_filter = normalize_container_filter(container_type)
    params: list[object] = []
    where = ""
    if selected_filter != "all":
        where = "WHERE lower(coalesce(items.container_type, '')) = ?"
        params.append(selected_filter)

    total_local = conn.execute("SELECT COUNT(*) FROM business_catalog_items").fetchone()[0]
    last_catalog_sync_at = conn.execute("SELECT MAX(last_catalog_sync_at) FROM business_catalog_items").fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT
            items.product_id,
            items.variant_id,
            items.slug,
            items.public_name,
            items.image_url,
            items.price_minor,
            items.currency,
            items.container_type,
            items.volume_liters,
            items.availability_status,
            items.last_catalog_sync_at,
            overrides.short_description,
            overrides.allow_preorder,
            overrides.min_order_quantity,
            overrides.order_step,
            products.article,
            products.code
        FROM business_catalog_items AS items
        LEFT JOIN product_overrides AS overrides ON overrides.product_id = items.product_id
        LEFT JOIN products ON products.id = items.product_id
        {where}
        ORDER BY items.sort_order ASC, items.public_name ASC
        """,
        params,
    ).fetchall()
    counts = {
        row["container_type"] or "unknown": row["count"]
        for row in conn.execute(
            """
            SELECT coalesce(container_type, 'unknown') AS container_type, COUNT(*) AS count
            FROM business_catalog_items
            GROUP BY coalesce(container_type, 'unknown')
            """
        ).fetchall()
    }
    items = []
    for row in rows:
        availability = row["availability_status"] or "unavailable"
        container = row["container_type"] or "unknown"
        items.append(
            {
                "productId": row["product_id"],
                "variantId": row["variant_id"],
                "slug": row["slug"],
                "name": row["public_name"],
                "subtitle": row["short_description"] or "Позиция локального B2B-каталога Stamm Brewing",
                "sku": row["article"] or row["code"],
                "containerType": container,
                "containerLabel": CONTAINER_LABELS.get(container, container or "Тара не указана"),
                "volumeLiters": row["volume_liters"],
                "price": _price_payload(row["price_minor"], row["currency"]),
                "availability": {
                    "status": availability,
                    "label": AVAILABILITY_LABELS.get(availability, availability),
                },
                "imageUrl": row["image_url"],
                "ctaLabel": "В заявку" if availability != "unavailable" or row["allow_preorder"] else "Недоступно",
                "orderRules": {
                    "allowPreorder": bool(row["allow_preorder"]),
                    "minQuantity": row["min_order_quantity"] or 1,
                    "step": row["order_step"] or 1,
                },
            }
        )
    return {
        "items": items,
        "filters": [
            {"value": "all", "label": "Все", "count": total_local},
            {"value": "keg", "label": "Кеги", "count": counts.get("keg", 0)},
            {"value": "can", "label": "Банки", "count": counts.get("can", 0)},
        ],
        "meta": {
            "source": "local_read_model",
            "readModel": "business_catalog_items",
            "selectedFilter": selected_filter,
            "totalLocalItems": total_local,
            "returnedItems": len(items),
            "lastCatalogSyncAt": last_catalog_sync_at,
            "status": "empty" if total_local == 0 else "ready",
        },
    }
