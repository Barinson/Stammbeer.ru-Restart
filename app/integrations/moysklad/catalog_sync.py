from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.integrations.moysklad.client import MoyskladClient, normalize_api_reference
from app.integrations.moysklad.settings_service import decode_token, get_settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def money_to_minor(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def infer_container_type(row: dict[str, Any]) -> str | None:
    text = " ".join(str(value or "") for value in (row.get("name"), row.get("article"), row.get("code"))).lower()
    if "кег" in text or "keg" in text:
        return "keg"
    if "банк" in text or "can" in text:
        return "can"
    if "бут" in text or "bottle" in text:
        return "bottle"
    return None


def extract_price_minor(row: dict[str, Any]) -> int | None:
    prices = row.get("salePrices") or []
    if not prices:
        return None
    return money_to_minor(prices[0].get("value"))


def stock_for_href(stock_rows: list[dict[str, Any]], href: str) -> float:
    for row in stock_rows:
        assortment_href = ((row.get("assortment") or {}).get("meta") or {}).get("href")
        if assortment_href == href:
            try:
                return float(row.get("stock") or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def availability_for_stock(stock: float) -> str:
    if stock > 5:
        return "available"
    if stock > 0:
        return "limited"
    return "unavailable"


def product_folder_href(row: dict[str, Any]) -> str | None:
    return (((row.get("productFolder") or {}).get("meta") or {}).get("href"))


def product_folder_parent_href(row: dict[str, Any]) -> str | None:
    parent = row.get("parent") or row.get("productFolder") or {}
    return ((parent.get("meta") or {}).get("href"))


def build_descendant_folder_hrefs(source_folder_href: str, folder_rows: list[dict[str, Any]]) -> set[str]:
    descendants = {source_folder_href}
    changed = True
    while changed:
        changed = False
        for folder in folder_rows:
            href = normalize_api_reference(folder).get("href")
            parent_href = product_folder_parent_href(folder)
            if href and parent_href in descendants and href not in descendants:
                descendants.add(href)
                changed = True
    return descendants


def folder_matches(row: dict[str, Any], allowed_folder_hrefs: set[str]) -> bool:
    folder_href = product_folder_href(row)
    return bool(folder_href and folder_href in allowed_folder_hrefs)


def run_manual_catalog_sync(conn: sqlite3.Connection, user_id: int | None = None) -> dict[str, Any]:
    settings = get_settings(conn)
    token = decode_token(settings["encrypted_token"])
    if not token:
        raise ValueError("MoySklad token is not configured")
    if not settings["source_product_folder_href"]:
        raise ValueError("Product folder is not selected")
    if not settings["store_href"]:
        raise ValueError("Warehouse/store is not selected")

    now = utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO moysklad_sync_jobs (type, status, trigger_source, started_by_user_id, started_at, stats_json)
        VALUES ('manual_catalog', 'running', 'manual', ?, ?, '{}')
        """,
        (user_id, now),
    )
    job_id = cursor.lastrowid
    conn.commit()

    stats = {
        "found": 0,
        "created": 0,
        "updated": 0,
        "outOfScopeMarked": 0,
        "sourceFolderHref": settings["source_product_folder_href"],
        "storeHref": settings["store_href"],
        "includeChildFolders": bool(settings["include_child_folders"]),
    }
    try:
        client = MoyskladClient(token=token, api_base_url=settings["api_base_url"])
        folder_rows = client.fetch_product_folder_rows() if settings["include_child_folders"] else []
        allowed_folder_hrefs = build_descendant_folder_hrefs(settings["source_product_folder_href"], folder_rows) if settings["include_child_folders"] else {settings["source_product_folder_href"]}
        assortment_rows = client.fetch_assortment_rows()
        scoped_rows = [row for row in assortment_rows if folder_matches(row, allowed_folder_hrefs)]
        stock_rows = client.fetch_stock_rows(settings["store_href"])
        stats["folderScopeCount"] = len(allowed_folder_hrefs)
        stats["assortmentRowsScanned"] = len(assortment_rows)
        stats["found"] = len(scoped_rows)
        seen_hrefs: set[str] = set()
        for row in scoped_rows:
            reference = normalize_api_reference(row)
            href = reference["href"]
            seen_hrefs.add(href)
            stock = stock_for_href(stock_rows, href)
            price_minor = extract_price_minor(row)
            container_type = infer_container_type(row)
            folder_href = product_folder_href(row)
            existing = conn.execute("SELECT id FROM products WHERE external_href = ?", (href,)).fetchone()
            if existing:
                product_id = existing["id"]
                stats["updated"] += 1
                conn.execute(
                    """
                    UPDATE products
                    SET external_id = ?, accounting_name = ?, code = ?, article = ?, external_code = ?,
                        container_type = ?, price_minor = ?, currency = 'RUB', stock_quantity = ?,
                        availability_status = ?, source_store_href = ?, source_folder_href = ?, sync_state = 'active',
                        sync_updated_at = ?, last_synced_at = ?
                    WHERE id = ?
                    """,
                    (
                        reference["id"], row.get("name") or reference["name"], row.get("code"), row.get("article"),
                        row.get("externalCode"), container_type, price_minor, stock, availability_for_stock(stock),
                        settings["store_href"], folder_href, row.get("updated"), now, product_id,
                    ),
                )
            else:
                stats["created"] += 1
                cursor = conn.execute(
                    """
                    INSERT INTO products (
                        external_id, external_href, accounting_name, code, article, external_code,
                        container_type, price_minor, currency, stock_quantity, availability_status,
                        source_store_href, source_folder_href, sync_state, sync_updated_at, last_synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RUB', ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        reference["id"], href, row.get("name") or reference["name"], row.get("code"), row.get("article"),
                        row.get("externalCode"), container_type, price_minor, stock, availability_for_stock(stock),
                        settings["store_href"], folder_href, row.get("updated"), now,
                    ),
                )
                product_id = cursor.lastrowid
                conn.execute(
                    """
                    INSERT OR IGNORE INTO product_overrides (product_id, public_name, slug, is_published)
                    VALUES (?, ?, ?, 0)
                    """,
                    (product_id, row.get("name") or reference["name"], f"product-{product_id}"),
                )
            conn.execute(
                """
                INSERT INTO inventory_snapshots (sync_job_id, product_id, store_external_id, stock, available_quantity, captured_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_id, product_id, settings["store_href"], stock, stock, now),
            )
        if seen_hrefs:
            placeholders = ",".join("?" for _ in seen_hrefs)
            folder_placeholders = ",".join("?" for _ in allowed_folder_hrefs)
            params = [*allowed_folder_hrefs, *seen_hrefs]
            out_rows = conn.execute(
                f"""
                SELECT id FROM products
                WHERE source_folder_href IN ({folder_placeholders}) AND external_href NOT IN ({placeholders}) AND sync_state = 'active'
                """,
                params,
            ).fetchall()
            stats["outOfScopeMarked"] = len(out_rows)
            conn.execute(
                f"""
                UPDATE products SET sync_state = 'out_of_scope', last_synced_at = ?
                WHERE source_folder_href IN ({folder_placeholders}) AND external_href NOT IN ({placeholders})
                """,
                [now, *params],
            )
        finished = utc_now_iso()
        conn.execute(
            """
            UPDATE moysklad_sync_jobs
            SET status = 'success', finished_at = ?, stats_json = ?
            WHERE id = ?
            """,
            (finished, json.dumps(stats, ensure_ascii=False), job_id),
        )
        conn.execute(
            """
            INSERT INTO moysklad_sync_logs (job_id, level, stage, entity_type, external_href, message, payload_excerpt_json)
            VALUES (?, 'info', 'manual_catalog_sync', 'assortment', ?, ?, ?)
            """,
            (
                job_id,
                settings["source_product_folder_href"],
                f"Manual catalog sync finished: {stats['found']} SKU found",
                json.dumps(stats, ensure_ascii=False),
            ),
        )
        conn.commit()
        return {"jobId": job_id, "status": "success", "stats": stats}
    except Exception as exc:
        finished = utc_now_iso()
        conn.execute(
            """
            UPDATE moysklad_sync_jobs
            SET status = 'failed', finished_at = ?, error_summary = ?
            WHERE id = ?
            """,
            (finished, str(exc), job_id),
        )
        conn.execute(
            """
            INSERT INTO moysklad_sync_logs (job_id, level, stage, message, error_code)
            VALUES (?, 'error', 'manual_catalog_sync', ?, 'MANUAL_SYNC_FAILED')
            """,
            (job_id, str(exc)),
        )
        conn.commit()
        raise
