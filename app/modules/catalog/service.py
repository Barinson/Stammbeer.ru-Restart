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
    conditions = [
        "products.sync_state = 'active'",
        "coalesce(products.stock_quantity, 0) > 0",
        "items.availability_status != 'unavailable'",
    ]
    if selected_filter != "all":
        conditions.append("lower(coalesce(items.container_type, '')) = ?")
        params.append(selected_filter)
    where = "WHERE " + " AND ".join(conditions)

    total_local = conn.execute(
        """
        SELECT COUNT(*)
        FROM business_catalog_items AS items
        JOIN products ON products.id = items.product_id
        WHERE products.sync_state = 'active'
          AND coalesce(products.stock_quantity, 0) > 0
          AND items.availability_status != 'unavailable'
        """
    ).fetchone()[0]
    last_catalog_sync_at = conn.execute(
        """
        SELECT MAX(items.last_catalog_sync_at)
        FROM business_catalog_items AS items
        JOIN products ON products.id = items.product_id
        WHERE products.sync_state = 'active'
          AND coalesce(products.stock_quantity, 0) > 0
          AND items.availability_status != 'unavailable'
        """
    ).fetchone()[0]
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
        JOIN products ON products.id = items.product_id
        {where}
        ORDER BY items.sort_order ASC, items.public_name ASC
        """,
        params,
    ).fetchall()
    counts = {
        row["container_type"] or "unknown": row["count"]
        for row in conn.execute(
            """
            SELECT coalesce(items.container_type, 'unknown') AS container_type, COUNT(*) AS count
            FROM business_catalog_items AS items
            JOIN products ON products.id = items.product_id
            WHERE products.sync_state = 'active'
              AND coalesce(products.stock_quantity, 0) > 0
              AND items.availability_status != 'unavailable'
            GROUP BY coalesce(items.container_type, 'unknown')
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


def admin_catalog_items(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            products.id,
            products.accounting_name,
            products.article,
            products.code,
            products.container_type,
            products.volume_liters,
            products.price_minor,
            products.currency,
            products.stock_quantity,
            coalesce(latest_inventory.available_quantity, products.stock_quantity) AS available_quantity,
            latest_inventory.stock AS latest_stock,
            latest_inventory.reserve AS latest_reserve,
            latest_inventory.in_transit AS latest_in_transit,
            products.availability_status,
            products.source_folder_href,
            products.source_store_href,
            products.sync_state,
            products.last_synced_at,
            product_overrides.is_published,
            product_overrides.public_name,
            product_overrides.slug
        FROM products
        LEFT JOIN product_overrides ON product_overrides.product_id = products.id
        LEFT JOIN inventory_snapshots AS latest_inventory
          ON latest_inventory.id = (
              SELECT id FROM inventory_snapshots
              WHERE product_id = products.id
              ORDER BY captured_at DESC, id DESC
              LIMIT 1
          )
        WHERE products.sync_state = 'active'
          AND coalesce(latest_inventory.available_quantity, products.stock_quantity, 0) > 0
          AND products.availability_status != 'unavailable'
        ORDER BY products.last_synced_at DESC, products.accounting_name ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def publish_product(conn: sqlite3.Connection, product_id: int, publish: bool) -> None:
    product = conn.execute(
        """
        SELECT id, accounting_name, stock_quantity, availability_status, sync_state
        FROM products
        WHERE id = ?
        """,
        (product_id,),
    ).fetchone()
    if not product:
        raise ValueError("Product not found")
    if publish and (product["sync_state"] != "active" or (product["stock_quantity"] or 0) <= 0 or product["availability_status"] == "unavailable"):
        raise ValueError("Only products with positive available stock can be published")
    slug = f"product-{product_id}"
    conn.execute(
        """
        INSERT INTO product_overrides (product_id, public_name, slug, is_published)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(product_id) DO UPDATE SET
            is_published = excluded.is_published,
            updated_at = CURRENT_TIMESTAMP
        """,
        (product_id, product["accounting_name"], slug, 1 if publish else 0),
    )
    if publish:
        conn.execute(
            """
            INSERT INTO business_catalog_items (
                product_id, slug, public_name, price_minor, currency, container_type,
                volume_liters, availability_status, sort_order, search_text, last_catalog_sync_at
            )
            SELECT
                products.id,
                coalesce(product_overrides.slug, ?),
                coalesce(product_overrides.public_name, products.accounting_name),
                products.price_minor,
                products.currency,
                products.container_type,
                products.volume_liters,
                products.availability_status,
                product_overrides.sort_order,
                products.accounting_name,
                products.last_synced_at
            FROM products
            JOIN product_overrides ON product_overrides.product_id = products.id
            WHERE products.id = ?
            ON CONFLICT(slug) DO UPDATE SET
                public_name = excluded.public_name,
                price_minor = excluded.price_minor,
                currency = excluded.currency,
                container_type = excluded.container_type,
                volume_liters = excluded.volume_liters,
                availability_status = excluded.availability_status,
                search_text = excluded.search_text,
                last_catalog_sync_at = excluded.last_catalog_sync_at
            """,
            (slug, product_id),
        )
    else:
        conn.execute("DELETE FROM business_catalog_items WHERE product_id = ?", (product_id,))
    conn.commit()
