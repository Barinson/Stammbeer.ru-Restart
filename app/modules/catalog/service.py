from __future__ import annotations

import sqlite3
from typing import Any
import json

CONTAINER_LABELS = {
    "keg": "Кеги",
    "can": "Банки",
}

AVAILABILITY_LABELS = {
    "available": "В наличии",
    "limited": "Мало",
    "preorder": "Предзаказ",
    "unavailable": "Нет в наличии",
    "hidden": "Скрыто",
}

PUBLIC_FILTERS = {"all", "keg", "can"}
DEFAULT_MIN_ORDER_AMOUNT_MINOR = 1_500_000
UNGROUPED_STYLE = {"id": None, "name": "Другие сорта", "sortOrder": 100000, "isVisible": True}


def normalize_container_filter(value: str | None) -> str:
    if not value:
        return "all"
    value = value.strip().lower()
    return value if value in PUBLIC_FILTERS else "all"


def business_min_order_amount_minor(value: object | None = None) -> int:
    raw_value = DEFAULT_MIN_ORDER_AMOUNT_MINOR if value is None or value == "" else value
    try:
        amount = int(str(raw_value))
    except (TypeError, ValueError):
        amount = DEFAULT_MIN_ORDER_AMOUNT_MINOR
    return max(0, amount)


def normalize_business_container_type(container_type: object = None, *source_values: object) -> str:
    explicit = str(container_type or "").strip().lower()
    if explicit in CONTAINER_LABELS:
        return explicit
    text = " ".join(str(value or "") for value in (container_type, *source_values)).lower()
    compact = text.replace(" ", "").replace(",", ".")
    can_markers = ("банка", "can", "0.33", "0.45", "0.5л")
    return "can" if any(marker in compact for marker in can_markers) else "keg"


def order_rules_for_container(container_type: str, min_quantity: object = None, order_step: object = None) -> dict[str, int]:
    if container_type == "can":
        return {"minQuantity": 12, "step": 12}
    try:
        minimum = max(1, int(min_quantity or 1))
    except (TypeError, ValueError):
        minimum = 1
    try:
        step = max(1, int(order_step or 1))
    except (TypeError, ValueError):
        step = 1
    return {"minQuantity": minimum, "step": step}


def _stock_quantity(value: object) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _price_type_prices(price_type_prices_json: str | None) -> list[dict[str, Any]]:
    if not price_type_prices_json:
        return []
    try:
        prices = json.loads(price_type_prices_json)
    except (TypeError, ValueError):
        return []
    return prices if isinstance(prices, list) else []


def _matched_price_type_price(
    prices: list[dict[str, Any]],
    price_type_href: str | None = None,
    price_type_id: str | None = None,
    price_type_name: str | None = None,
) -> dict[str, Any] | None:
    normalized_name = str(price_type_name or "").strip().lower()
    for price in prices:
        if price.get("value") is None:
            continue
        if price_type_href and price.get("priceTypeHref") == price_type_href:
            return price
        if price_type_id and price.get("priceTypeId") == price_type_id:
            return price
        if normalized_name and str(price.get("priceTypeName") or "").strip().lower() == normalized_name:
            return price
    return None


def _price_payload(
    price_minor: int | None,
    currency: str | None,
    discount_percent: float = 0.0,
    personal_price_minor: int | None = None,
    price_type_name: str | None = None,
) -> dict[str, Any]:
    if price_minor is None and personal_price_minor is None:
        return {"visibility": "hidden", "label": "Цена по запросу"}
    base_minor = price_minor if price_minor is not None else personal_price_minor
    normalized_discount = max(0.0, min(float(discount_percent or 0), 100.0))
    if personal_price_minor is not None:
        effective_minor = personal_price_minor
        pricing_source = "price_type"
    else:
        effective_minor = round(int(base_minor) * (100 - normalized_discount) / 100)
        pricing_source = "discount" if normalized_discount else "base"
    show_base_price = int(base_minor) != int(effective_minor)
    return {
        "visibility": "public",
        "amountMinor": effective_minor,
        "baseAmountMinor": base_minor,
        "currency": currency or "RUB",
        "label": f"{effective_minor / 100:,.0f} ₽".replace(",", " "),
        "baseLabel": f"{int(base_minor) / 100:,.0f} ₽".replace(",", " "),
        "showBasePrice": show_base_price,
        "discountPercent": normalized_discount if personal_price_minor is None else 0.0,
        "priceTypeName": price_type_name if personal_price_minor is not None else None,
        "pricingSource": pricing_source,
        "isPersonalized": personal_price_minor is not None or normalized_discount > 0,
    }




def sync_business_catalog_read_model(conn: sqlite3.Connection) -> None:
    """Keep the public B2B read-model exactly aligned with admin publication flags."""
    conn.execute(
        """
        DELETE FROM business_catalog_items
        WHERE product_id NOT IN (
            SELECT products.id
            FROM products
            JOIN product_overrides ON product_overrides.product_id = products.id
            WHERE coalesce(product_overrides.is_published, 0) = 1
              AND products.sync_state = 'active'
              AND coalesce(products.stock_quantity, 0) > 0
              AND products.availability_status != 'unavailable'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO business_catalog_items (
            product_id, slug, public_name, image_url, price_minor, price_type_prices_json, currency, container_type,
            volume_liters, alcohol_percent, availability_status, sort_order, search_text, last_catalog_sync_at
        )
        SELECT
            products.id,
            coalesce(product_overrides.slug, (SELECT slug FROM business_catalog_items WHERE product_id = products.id ORDER BY id LIMIT 1), 'product-' || products.id),
            coalesce(nullif(product_overrides.public_name, ''), products.accounting_name),
            products.image_url,
            coalesce((SELECT keep.price_minor FROM business_catalog_items AS keep WHERE keep.product_id = products.id ORDER BY keep.id LIMIT 1), products.price_minor),
            coalesce((SELECT keep.price_type_prices_json FROM business_catalog_items AS keep WHERE keep.product_id = products.id ORDER BY keep.id LIMIT 1), products.price_type_prices_json),
            products.currency,
            coalesce(nullif(product_overrides.container_type_override, ''), products.container_type),
            products.volume_liters,
            products.alcohol_percent,
            products.availability_status,
            product_overrides.sort_order,
            products.accounting_name,
            products.last_synced_at
        FROM products
        JOIN product_overrides ON product_overrides.product_id = products.id
        WHERE coalesce(product_overrides.is_published, 0) = 1
          AND products.sync_state = 'active'
          AND coalesce(products.stock_quantity, 0) > 0
          AND products.availability_status != 'unavailable'
        ON CONFLICT(slug) DO UPDATE SET
            product_id = excluded.product_id,
            public_name = excluded.public_name,
            image_url = excluded.image_url,
            price_minor = excluded.price_minor,
            price_type_prices_json = excluded.price_type_prices_json,
            currency = excluded.currency,
            container_type = excluded.container_type,
            volume_liters = excluded.volume_liters,
            alcohol_percent = excluded.alcohol_percent,
            availability_status = excluded.availability_status,
            sort_order = excluded.sort_order,
            search_text = excluded.search_text,
            last_catalog_sync_at = excluded.last_catalog_sync_at
        """
    )

    conn.execute(
        """
        DELETE FROM business_catalog_items
        WHERE product_id IN (
            SELECT products.id
            FROM products
            JOIN product_overrides ON product_overrides.product_id = products.id
            WHERE coalesce(product_overrides.is_published, 0) = 1
              AND products.sync_state = 'active'
              AND coalesce(products.stock_quantity, 0) > 0
              AND products.availability_status != 'unavailable'
        )
          AND slug NOT IN (
            SELECT coalesce(
                product_overrides.slug,
                (SELECT keep.slug FROM business_catalog_items AS keep WHERE keep.product_id = products.id ORDER BY keep.id LIMIT 1),
                'product-' || products.id
            )
            FROM products
            JOIN product_overrides ON product_overrides.product_id = products.id
            WHERE coalesce(product_overrides.is_published, 0) = 1
              AND products.sync_state = 'active'
              AND coalesce(products.stock_quantity, 0) > 0
              AND products.availability_status != 'unavailable'
        )
        """
    )

def public_catalog(
    conn: sqlite3.Connection,
    container_type: str | None = None,
    customer_discount_percent: float = 0.0,
    customer_price_type_href: str | None = None,
    customer_price_type_id: str | None = None,
    customer_price_type_name: str | None = None,
    minimum_order_amount_minor: int | None = None,
) -> dict[str, Any]:
    sync_business_catalog_read_model(conn)
    selected_filter = normalize_container_filter(container_type)
    params: list[object] = []
    conditions = [
        "coalesce(overrides.is_published, 0) = 1",
        "products.sync_state = 'active'",
        "coalesce(products.stock_quantity, 0) > 0",
        "items.availability_status != 'unavailable'",
    ]
    where = "WHERE " + " AND ".join(conditions)

    total_local = conn.execute(
        """
        SELECT COUNT(*)
        FROM business_catalog_items AS items
        JOIN products ON products.id = items.product_id
        LEFT JOIN product_overrides AS overrides ON overrides.product_id = items.product_id
        WHERE coalesce(overrides.is_published, 0) = 1
          AND products.sync_state = 'active'
          AND coalesce(products.stock_quantity, 0) > 0
          AND items.availability_status != 'unavailable'
        """
    ).fetchone()[0]
    last_catalog_sync_at = conn.execute(
        """
        SELECT MAX(items.last_catalog_sync_at)
        FROM business_catalog_items AS items
        JOIN products ON products.id = items.product_id
        LEFT JOIN product_overrides AS overrides ON overrides.product_id = items.product_id
        WHERE coalesce(overrides.is_published, 0) = 1
          AND products.sync_state = 'active'
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
            items.price_type_prices_json,
            products.price_minor AS product_price_minor,
            products.price_type_prices_json AS product_price_type_prices_json,
            products.external_id,
            products.external_href,
            items.currency,
            items.container_type,
            items.volume_liters,
            items.alcohol_percent AS item_alcohol_percent,
            products.alcohol_percent AS product_alcohol_percent,
            items.availability_status,
            items.last_catalog_sync_at,
            overrides.short_description,
            overrides.allow_preorder,
            overrides.min_order_quantity,
            overrides.order_step,
            products.stock_quantity,
            products.article,
            products.code,
            styles.id AS beer_style_id,
            styles.name AS beer_style_name,
            styles.sort_order AS beer_style_sort_order
        FROM business_catalog_items AS items
        LEFT JOIN product_overrides AS overrides ON overrides.product_id = items.product_id
        LEFT JOIN beer_styles AS styles ON styles.id = overrides.beer_style_id AND styles.is_visible = 1
        JOIN products ON products.id = items.product_id
        {where}
        ORDER BY coalesce(styles.sort_order, 100000) ASC, coalesce(styles.name, 'zzz') ASC, items.sort_order ASC, items.public_name ASC
        """,
        params,
    ).fetchall()
    counts = {"keg": 0, "can": 0}
    for row in conn.execute(
            """
            SELECT items.container_type, items.public_name, products.article, products.code
            FROM business_catalog_items AS items
            JOIN products ON products.id = items.product_id
            LEFT JOIN product_overrides AS overrides ON overrides.product_id = items.product_id
            WHERE coalesce(overrides.is_published, 0) = 1
              AND products.sync_state = 'active'
              AND coalesce(products.stock_quantity, 0) > 0
              AND items.availability_status != 'unavailable'
            """
    ).fetchall():
        normalized_container = normalize_business_container_type(
            row["container_type"], row["public_name"], row["article"], row["code"]
        )
        counts[normalized_container] = counts.get(normalized_container, 0) + 1
    items = []
    price_debug_sample = []
    for row in rows:
        availability = row["availability_status"] or "unavailable"
        container = normalize_business_container_type(row["container_type"], row["public_name"], row["article"], row["code"])
        if selected_filter != "all" and container != selected_filter:
            continue
        order_rules = order_rules_for_container(container, row["min_order_quantity"], row["order_step"])
        available_quantity = _stock_quantity(row["stock_quantity"])
        price_type_prices = _price_type_prices(row["price_type_prices_json"]) or _price_type_prices(row["product_price_type_prices_json"])
        base_price_minor = row["price_minor"] if row["price_minor"] is not None else row["product_price_minor"]
        matched_price_type_price = _matched_price_type_price(
            price_type_prices,
            customer_price_type_href,
            customer_price_type_id,
            customer_price_type_name,
        )
        price_payload = _price_payload(
            base_price_minor,
            row["currency"],
            customer_discount_percent,
            int(matched_price_type_price["value"]) if matched_price_type_price is not None else None,
            customer_price_type_name,
        )
        alcohol_percent = row["item_alcohol_percent"] if row["item_alcohol_percent"] is not None else row["product_alcohol_percent"]
        alcohol_label = None
        if alcohol_percent is not None:
            try:
                alcohol_label = f"{float(alcohol_percent):g}%".replace(".", ",")
            except (TypeError, ValueError):
                alcohol_label = None
        price_diagnostics = {
            "basePriceMinor": base_price_minor,
            "availablePriceTypes": price_type_prices,
            "matchedPriceType": matched_price_type_price,
            "returnedAmountMinor": price_payload.get("amountMinor"),
            "pricingSource": price_payload.get("pricingSource"),
            "priceTypeName": price_payload.get("priceTypeName"),
        }
        if len(price_debug_sample) < 10:
            price_debug_sample.append(
                {
                    "skuName": row["public_name"],
                    "basePriceMinor": base_price_minor,
                    "availablePriceTypes": price_type_prices,
                    "matchedPriceType": matched_price_type_price,
                    "returnedAmountMinor": price_payload.get("amountMinor"),
                    "pricingSource": price_payload.get("pricingSource"),
                    "priceTypeName": price_payload.get("priceTypeName"),
                }
            )
        items.append(
            {
                "productId": row["product_id"],
                "variantId": row["variant_id"],
                "slug": row["slug"],
                "name": row["public_name"],
                "subtitle": row["short_description"] or "",
                "sku": row["article"] or row["code"],
                "externalId": row["external_id"],
                "externalHref": row["external_href"],
                "containerType": container,
                "containerLabel": CONTAINER_LABELS.get(container, container or "Тара не указана"),
                "volumeLiters": row["volume_liters"],
                "alcoholPercent": alcohol_percent,
                "alcoholLabel": alcohol_label,
                "price": price_payload,
                "priceDiagnostics": price_diagnostics,
                "availability": {
                    "status": availability,
                    "label": AVAILABILITY_LABELS.get(availability, availability),
                    "quantity": available_quantity,
                },
                "imageUrl": row["image_url"],
                "style": {
                    "id": row["beer_style_id"],
                    "name": row["beer_style_name"] or UNGROUPED_STYLE["name"],
                    "sortOrder": row["beer_style_sort_order"] if row["beer_style_sort_order"] is not None else UNGROUPED_STYLE["sortOrder"],
                },
                "ctaLabel": "В заявку" if availability != "unavailable" or row["allow_preorder"] else "Недоступно",
                "orderRules": {
                    "allowPreorder": bool(row["allow_preorder"]),
                    "minQuantity": order_rules["minQuantity"],
                    "step": order_rules["step"],
                    "maxQuantity": available_quantity,
                },
            }
        )
    style_groups: dict[str, dict[str, Any]] = {}
    for item in items:
        style = item["style"]
        key = str(style.get("id") or "ungrouped")
        if key not in style_groups:
            style_groups[key] = {"id": style.get("id"), "name": style.get("name"), "sortOrder": style.get("sortOrder"), "count": 0, "itemsCount": 0}
        style_groups[key]["count"] += 1
        style_groups[key]["itemsCount"] += 1
    styles = sorted(style_groups.values(), key=lambda style: (int(style.get("sortOrder") or 100000), str(style.get("name") or "")))
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
            "styles": styles,
            "lastCatalogSyncAt": last_catalog_sync_at,
            "status": "empty" if total_local == 0 else "ready",
            "pricingMode": "personal" if customer_discount_percent or customer_price_type_href or customer_price_type_id or customer_price_type_name else "base",
            "customerDiscountPercent": max(0.0, min(float(customer_discount_percent or 0), 100.0)),
            "customerPriceType": {
                "id": customer_price_type_id,
                "href": customer_price_type_href,
                "name": customer_price_type_name,
            },
            "priceDebugSample": price_debug_sample,
            "minimumOrder": {
                "amountMinor": business_min_order_amount_minor(minimum_order_amount_minor),
                "label": f"{business_min_order_amount_minor(minimum_order_amount_minor) / 100:,.0f} ₽".replace(",", " "),
            },
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
            product_overrides.container_type_override,
            products.volume_liters,
            products.price_minor,
            products.currency,
            products.image_url,
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
            product_overrides.slug,
            product_overrides.beer_style_id,
            beer_styles.name AS beer_style_name
        FROM products
        LEFT JOIN product_overrides ON product_overrides.product_id = products.id
        LEFT JOIN beer_styles ON beer_styles.id = product_overrides.beer_style_id
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


def assign_product_container_type(conn: sqlite3.Connection, product_id: int, container_type: object) -> None:
    normalized = str(container_type or "").strip().lower()
    if normalized not in CONTAINER_LABELS:
        raise ValueError("Выберите корректный тип тары.")
    product = conn.execute("SELECT id, accounting_name FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        raise ValueError("Product not found")
    existing = conn.execute("SELECT * FROM product_overrides WHERE product_id = ?", (product_id,)).fetchone()
    public_name = existing["public_name"] if existing and existing["public_name"] else product["accounting_name"]
    slug = existing["slug"] if existing and existing["slug"] else f"product-{product_id}"
    is_published = int(existing["is_published"]) if existing else 0
    conn.execute(
        """
        INSERT INTO product_overrides (product_id, public_name, slug, is_published, container_type_override)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(product_id) DO UPDATE SET
            container_type_override = excluded.container_type_override,
            updated_at = CURRENT_TIMESTAMP
        """,
        (product_id, public_name, slug, is_published, normalized),
    )
    sync_business_catalog_read_model(conn)
    conn.commit()


def beer_styles(conn: sqlite3.Connection, include_hidden: bool = True) -> list[dict[str, Any]]:
    where = "" if include_hidden else "WHERE is_visible = 1"
    rows = conn.execute(
        f"SELECT id, name, sort_order, is_visible FROM beer_styles {where} ORDER BY sort_order ASC, name ASC"
    ).fetchall()
    return [dict(row) for row in rows]


def save_beer_style(conn: sqlite3.Connection, name: str, sort_order: object = 100, is_visible: bool = True, style_id: object | None = None) -> None:
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("Укажите название стиля пива.")
    try:
        order = int(str(sort_order or 100))
    except (TypeError, ValueError):
        order = 100
    if style_id:
        conn.execute(
            """
            UPDATE beer_styles
            SET name = ?, sort_order = ?, is_visible = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (clean_name, order, 1 if is_visible else 0, int(style_id)),
        )
    else:
        conn.execute(
            "INSERT INTO beer_styles (name, sort_order, is_visible) VALUES (?, ?, ?)",
            (clean_name, order, 1 if is_visible else 0),
        )
    conn.commit()


def assign_product_beer_style(conn: sqlite3.Connection, product_id: int, style_id: object | None) -> None:
    product = conn.execute("SELECT id, accounting_name FROM products WHERE id = ?", (product_id,)).fetchone()
    if product is None:
        raise ValueError("Product not found")
    normalized_style_id = int(style_id) if str(style_id or "").strip().isdigit() else None
    existing = conn.execute("SELECT * FROM product_overrides WHERE product_id = ?", (product_id,)).fetchone()
    public_name = existing["public_name"] if existing and existing["public_name"] else product["accounting_name"]
    slug = existing["slug"] if existing and existing["slug"] else f"product-{product_id}"
    is_published = int(existing["is_published"]) if existing else 0
    conn.execute(
        """
        INSERT INTO product_overrides (product_id, public_name, slug, is_published, beer_style_id)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(product_id) DO UPDATE SET
            beer_style_id = excluded.beer_style_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        (product_id, public_name, slug, is_published, normalized_style_id),
    )
    sync_business_catalog_read_model(conn)
    conn.commit()


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
    sync_business_catalog_read_model(conn)
    conn.commit()
