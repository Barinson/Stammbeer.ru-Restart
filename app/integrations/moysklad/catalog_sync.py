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
    compact = text.replace(" ", "")
    if "кег" in text or "keg" in text:
        return "keg"
    if ("10л" in compact or "20л" in compact or "10l" in compact or "20l" in compact) and ("(s)" in compact or "(a)" in compact):
        return "keg"
    if "банк" in text or "can" in text:
        return "can"
    if "бут" in text or "bottle" in text:
        return "bottle"
    return None


def extract_sale_price_minor(row: dict[str, Any]) -> int | None:
    """Return MoySklad "Цена продажи" for one SKU in minor money units."""
    for price in row.get("salePrices") or []:
        price_type = price.get("priceType") or {}
        price_type_name = str(price_type.get("name") or price.get("priceTypeName") or "").strip().lower()
        if price_type_name == "цена продажи":
            return money_to_minor(price.get("value"))
    return None



def image_url_from_image_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("miniature", "tiny", "meta"):
        nested = payload.get(key) or {}
        if isinstance(nested, dict):
            url = nested.get("downloadHref") or nested.get("href")
            if url:
                return str(url)
    for key in ("downloadHref", "href", "url", "imageUrl"):
        if payload.get(key):
            return str(payload[key])
    return None


def extract_image_url(row: dict[str, Any]) -> str | None:
    for key in ("imageUrl", "image_url", "picture", "photo"):
        if row.get(key):
            return str(row[key])
    image = row.get("image")
    if isinstance(image, dict):
        url = image_url_from_image_payload(image)
        if url:
            return url
    for collection_key in ("images", "files"):
        collection = row.get(collection_key)
        rows = collection.get("rows") if isinstance(collection, dict) else collection
        if isinstance(rows, list):
            for item in rows:
                url = image_url_from_image_payload(item)
                if url:
                    return url
    return None


def product_image_url(client: MoyskladClient, row: dict[str, Any], reference: dict[str, Any]) -> str | None:
    embedded = extract_image_url(row)
    if embedded:
        return embedded
    try:
        for image in client.fetch_assortment_images(reference["href"]):
            url = image_url_from_image_payload(image)
            if url:
                return url
    except Exception:
        return None
    return None

def number_value(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def stock_snapshot(row: dict[str, Any] | None) -> dict[str, float]:
    row = row or {}
    reserve = number_value(row.get("reserve"))
    in_transit = number_value(row.get("inTransit"))
    quantity = number_value(row.get("quantity"))
    if row.get("stock") is None and "quantity" in row:
        stock = quantity + reserve
    else:
        stock = number_value(row.get("stock"))
    # Match MoySklad's warehouse filter "Доступное": free availability is stock minus reserve.
    available = max(stock - reserve, 0.0)
    return {
        "stock": stock,
        "reserve": reserve,
        "inTransit": in_transit,
        "availableQuantity": available,
    }


def normalize_href_key(value: Any) -> str | None:
    if not value:
        return None
    return str(value).split("?", 1)[0]


def stock_row_keys(row: dict[str, Any]) -> set[str]:
    href_values = [
        ((row.get("assortment") or {}).get("meta") or {}).get("href"),
        (row.get("meta") or {}).get("href"),
    ]
    keys = {row.get("assortmentId"), row.get("id")}
    for href in href_values:
        if href:
            keys.add(str(href))
            keys.add(normalize_href_key(href))
    return {str(key) for key in keys if key}


def stock_by_store_snapshot(row: dict[str, Any], store_href: str) -> dict[str, float]:
    store_rows = row.get("stockByStore") or []
    if not store_rows:
        return stock_snapshot(row)
    aggregate = {"stock": 0.0, "reserve": 0.0, "inTransit": 0.0, "availableQuantity": 0.0}
    matched_store = False
    for store_row in store_rows:
        row_store_href = ((store_row.get("meta") or {}).get("href") or ((store_row.get("store") or {}).get("meta") or {}).get("href"))
        if row_store_href and row_store_href != store_href:
            continue
        matched_store = True
        snapshot = stock_snapshot(store_row)
        aggregate["stock"] += snapshot["stock"]
        aggregate["reserve"] += snapshot["reserve"]
        aggregate["inTransit"] += snapshot["inTransit"]
        aggregate["availableQuantity"] += snapshot["availableQuantity"]
    return aggregate if matched_store else stock_snapshot(None)


def stock_snapshots_by_key(stock_rows: list[dict[str, Any]], store_href: str) -> dict[str, dict[str, float]]:
    snapshots: dict[str, dict[str, float]] = {}
    for row in stock_rows:
        snapshot = stock_by_store_snapshot(row, store_href)
        for key in stock_row_keys(row):
            snapshots[key] = snapshot
    return snapshots



def reference_match_keys(reference: dict[str, Any]) -> tuple[str, ...]:
    keys = [reference["href"], normalize_href_key(reference["href"]), reference["id"]]
    return tuple(str(key) for key in keys if key)


def stock_snapshot_for_reference(reference: dict[str, Any], stock_by_key: dict[str, dict[str, float]]) -> tuple[dict[str, float], str | None]:
    for key in reference_match_keys(reference):
        if key in stock_by_key:
            return stock_by_key[key], key
    return stock_snapshot(None), None


def sku_diagnostic(row: dict[str, Any], reference: dict[str, Any], snapshot: dict[str, float], matched_key: str | None, decision: str) -> dict[str, Any]:
    available = snapshot["availableQuantity"]
    return {
        "sku": row.get("article") or row.get("code") or reference["id"],
        "name": row.get("name") or reference["name"],
        "href": reference["href"],
        "matched": bool(matched_key),
        "matchedKey": matched_key,
        "stock": snapshot["stock"],
        "reserve": snapshot["reserve"],
        "available": available,
        "decision": decision,
        "savedAvailable": available if decision == "import" else 0,
        "savedAvailabilityStatus": availability_for_stock(available) if decision == "import" else "not_imported_or_out_of_stock",
    }


def assortment_candidate_debug(row: dict[str, Any]) -> dict[str, Any]:
    reference = normalize_api_reference(row)
    return {
        "name": row.get("name") or reference["name"],
        "id": reference["id"],
        "href": reference["href"],
        "type": ((row.get("meta") or {}).get("type") or row.get("type")),
        "article": row.get("article"),
        "code": row.get("code"),
        "folderHref": product_folder_href(row),
        "imageUrl": extract_image_url(row),
    }


def stock_report_row_debug(row: dict[str, Any], store_href: str) -> dict[str, Any]:
    snapshot = stock_by_store_snapshot(row, store_href)
    store_rows = row.get("stockByStore") or []
    used_store_rows = []
    for store_row in store_rows:
        row_store_href = ((store_row.get("meta") or {}).get("href") or ((store_row.get("store") or {}).get("meta") or {}).get("href"))
        if not row_store_href or row_store_href == store_href:
            used_store_rows.append({
                "storeHref": row_store_href,
                "stock": number_value(store_row.get("stock")),
                "quantity": number_value(store_row.get("quantity")) if "quantity" in store_row else None,
                "reserve": number_value(store_row.get("reserve")),
                "inTransit": number_value(store_row.get("inTransit")),
                "rawKeys": sorted(store_row.keys()),
            })
    return {
        "name": row.get("name"),
        "id": row.get("id"),
        "assortmentId": row.get("assortmentId"),
        "href": (row.get("meta") or {}).get("href"),
        "keysUsedForMatch": sorted(stock_row_keys(row)),
        "store": store_href,
        "stock": snapshot["stock"],
        "reserve": snapshot["reserve"],
        "inTransit": snapshot["inTransit"],
        "available": snapshot["availableQuantity"],
        "rawKeys": sorted(row.keys()),
        "usedStockByStoreRows": used_store_rows,
    }


def db_write_debug(row: dict[str, Any], reference: dict[str, Any], snapshot: dict[str, float], action: str, product_id: int | None, reason: str | None = None) -> dict[str, Any]:
    available = snapshot["availableQuantity"]
    return {
        "name": row.get("name") or reference["name"],
        "id": reference["id"],
        "href": reference["href"],
        "productId": product_id,
        "action": action,
        "reason": reason,
        "savedStock": snapshot["stock"],
        "savedReserve": snapshot["reserve"],
        "savedAvailable": available,
        "savedAvailabilityStatus": availability_for_stock(available) if available > 0 else "unavailable",
    }


def latest_sync_diagnostics(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT payload_excerpt_json
        FROM moysklad_sync_logs
        WHERE stage = 'diagnostic_mode'
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    if not row or not row["payload_excerpt_json"]:
        return None
    return json.loads(row["payload_excerpt_json"])


def availability_for_stock(available_quantity: float) -> str:
    if available_quantity > 5:
        return "available"
    if available_quantity > 0:
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


def run_manual_catalog_sync(conn: sqlite3.Connection, user_id: int | None = None, diagnostic_mode: bool = False) -> dict[str, Any]:
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
        "diagnosticMode": diagnostic_mode,
        "imagesResolved": 0,
    }
    try:
        client = MoyskladClient(token=token, api_base_url=settings["api_base_url"])
        folder_rows = client.fetch_product_folder_rows() if settings["include_child_folders"] else []
        allowed_folder_hrefs = build_descendant_folder_hrefs(settings["source_product_folder_href"], folder_rows) if settings["include_child_folders"] else {settings["source_product_folder_href"]}
        assortment_rows = client.fetch_assortment_rows()
        scoped_rows = [row for row in assortment_rows if folder_matches(row, allowed_folder_hrefs)]
        stock_rows = client.fetch_stock_rows(settings["store_href"])
        stock_by_key = stock_snapshots_by_key(stock_rows, settings["store_href"])
        diagnostic_payload = {
            "settings": {
                "sourceFolderHref": settings["source_product_folder_href"],
                "storeHref": settings["store_href"],
                "includeChildFolders": bool(settings["include_child_folders"]),
            },
            "folderCandidates": [assortment_candidate_debug(row) for row in scoped_rows[:10]],
            "stockReportRows": [stock_report_row_debug(row, settings["store_href"]) for row in stock_rows[:10]],
            "matching": [],
            "dbWrites": [],
            "localCatalogAfterSync": [],
        }
        positive_rows: list[tuple[dict[str, Any], dict[str, float]]] = []
        non_positive_rows: list[tuple[dict[str, Any], dict[str, float]]] = []
        diagnostic_sample: list[dict[str, Any]] = []
        for row in scoped_rows:
            reference = normalize_api_reference(row)
            snapshot, matched_key = stock_snapshot_for_reference(reference, stock_by_key)
            if snapshot["availableQuantity"] > 0:
                positive_rows.append((row, snapshot))
                decision = "import"
            else:
                non_positive_rows.append((row, snapshot))
                decision = "skip_no_positive_availability"
            match_reason = "matched" if matched_key else "no stock row matched candidate href/id; fallback zero snapshot used"
            if len(diagnostic_sample) < 10:
                diagnostic_sample.append(sku_diagnostic(row, reference, snapshot, matched_key, decision))
            if diagnostic_mode and len(diagnostic_payload["matching"]) < 10:
                diagnostic_payload["matching"].append({
                    "candidateName": row.get("name") or reference["name"],
                    "candidateId": reference["id"],
                    "candidateHref": reference["href"],
                    "candidateMatchKeys": list(reference_match_keys(reference)),
                    "matched": bool(matched_key),
                    "matchedKey": matched_key,
                    "stock": snapshot["stock"],
                    "reserve": snapshot["reserve"],
                    "available": snapshot["availableQuantity"],
                    "decision": decision,
                    "reason": match_reason,
                })
        stats["folderScopeCount"] = len(allowed_folder_hrefs)
        stats["assortmentRowsScanned"] = len(assortment_rows)
        stats["folderMatched"] = len(scoped_rows)
        stats["stockRowsFetched"] = len(stock_rows)
        stats["stockMatched"] = sum(1 for item in diagnostic_sample if item["matched"])
        if len(scoped_rows) > len(diagnostic_sample):
            stats["stockMatched"] = sum(1 for row in scoped_rows if any(key in stock_by_key for key in reference_match_keys(normalize_api_reference(row))))
        stats["missingStockRows"] = len(scoped_rows) - stats["stockMatched"]
        stats["skippedNoPositiveAvailability"] = len(non_positive_rows)
        stats["diagnosticSample"] = diagnostic_sample
        stats["outOfStockMarked"] = 0
        stats["found"] = len(positive_rows)
        seen_hrefs: set[str] = set()
        for row, snapshot in positive_rows:
            reference = normalize_api_reference(row)
            href = reference["href"]
            seen_hrefs.add(href)
            available_quantity = snapshot["availableQuantity"]
            price_minor = extract_sale_price_minor(row)
            container_type = infer_container_type(row)
            folder_href = product_folder_href(row)
            image_url = product_image_url(client, row, reference)
            if image_url:
                stats["imagesResolved"] += 1
            existing = conn.execute("SELECT id FROM products WHERE external_href = ?", (href,)).fetchone()
            if existing:
                product_id = existing["id"]
                stats["updated"] += 1
                conn.execute(
                    """
                    UPDATE products
                    SET external_id = ?, accounting_name = ?, code = ?, article = ?, external_code = ?,
                        container_type = ?, price_minor = ?, currency = 'RUB', stock_quantity = ?, image_url = ?,
                        availability_status = ?, source_store_href = ?, source_folder_href = ?, sync_state = 'active',
                        sync_updated_at = ?, last_synced_at = ?
                    WHERE id = ?
                    """,
                    (
                        reference["id"], row.get("name") or reference["name"], row.get("code"), row.get("article"),
                        row.get("externalCode"), container_type, price_minor, available_quantity, image_url, availability_for_stock(available_quantity),
                        settings["store_href"], folder_href, row.get("updated"), now, product_id,
                    ),
                )
            else:
                stats["created"] += 1
                cursor = conn.execute(
                    """
                    INSERT INTO products (
                        external_id, external_href, accounting_name, code, article, external_code,
                        container_type, price_minor, currency, stock_quantity, image_url, availability_status,
                        source_store_href, source_folder_href, sync_state, sync_updated_at, last_synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RUB', ?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        reference["id"], href, row.get("name") or reference["name"], row.get("code"), row.get("article"),
                        row.get("externalCode"), container_type, price_minor, available_quantity, image_url, availability_for_stock(available_quantity),
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
                INSERT INTO inventory_snapshots (sync_job_id, product_id, store_external_id, stock, reserve, in_transit, available_quantity, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, product_id, settings["store_href"], snapshot["stock"], snapshot["reserve"], snapshot["inTransit"], snapshot["availableQuantity"], now),
            )
            if image_url:
                conn.execute("UPDATE business_catalog_items SET image_url = ? WHERE product_id = ?", (image_url, product_id))
            if diagnostic_mode and len(diagnostic_payload["dbWrites"]) < 10:
                entry = db_write_debug(row, reference, snapshot, "update" if existing else "create", product_id)
                entry["savedImageUrl"] = image_url
                diagnostic_payload["dbWrites"].append(entry)
        for row, snapshot in non_positive_rows:
            href = normalize_api_reference(row)["href"]
            existing = conn.execute("SELECT id FROM products WHERE external_href = ?", (href,)).fetchone()
            if not existing:
                if diagnostic_mode and len(diagnostic_payload["dbWrites"]) < 10:
                    diagnostic_payload["dbWrites"].append(db_write_debug(row, normalize_api_reference(row), snapshot, "skip", None, "available <= 0 and product does not exist locally"))
                continue
            stats["outOfStockMarked"] += 1
            conn.execute(
                """
                UPDATE products
                SET stock_quantity = ?, availability_status = 'unavailable', sync_state = 'out_of_stock',
                    source_store_href = ?, source_folder_href = ?, sync_updated_at = ?, last_synced_at = ?
                WHERE id = ?
                """,
                (snapshot["availableQuantity"], settings["store_href"], product_folder_href(row), row.get("updated"), now, existing["id"]),
            )
            conn.execute(
                """
                INSERT INTO inventory_snapshots (sync_job_id, product_id, store_external_id, stock, reserve, in_transit, available_quantity, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, existing["id"], settings["store_href"], snapshot["stock"], snapshot["reserve"], snapshot["inTransit"], snapshot["availableQuantity"], now),
            )
            conn.execute("DELETE FROM business_catalog_items WHERE product_id = ?", (existing["id"],))
            if diagnostic_mode and len(diagnostic_payload["dbWrites"]) < 10:
                diagnostic_payload["dbWrites"].append(db_write_debug(row, normalize_api_reference(row), snapshot, "mark_out_of_stock", existing["id"], "available <= 0"))
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
        if diagnostic_mode:
            diagnostic_payload["localCatalogAfterSync"] = [
                dict(row) for row in conn.execute(
                    """
                    SELECT products.id, products.accounting_name, products.external_href, products.stock_quantity,
                           products.availability_status, products.sync_state, products.last_synced_at
                    FROM products
                    WHERE products.source_store_href = ?
                    ORDER BY products.last_synced_at DESC, products.id DESC
                    LIMIT 10
                    """,
                    (settings["store_href"],),
                ).fetchall()
            ]
            stats["diagnosticPayload"] = diagnostic_payload
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
        conn.execute(
            """
            INSERT INTO moysklad_sync_logs (job_id, level, stage, entity_type, external_href, message, payload_excerpt_json)
            VALUES (?, 'info', 'stock_matching_debug', 'assortment', ?, ?, ?)
            """,
            (
                job_id,
                settings["source_product_folder_href"],
                f"Stock matching diagnostics: {stats['stockMatched']} matched / {stats['missingStockRows']} missing",
                json.dumps(diagnostic_sample, ensure_ascii=False),
            ),
        )
        if diagnostic_mode:
            conn.execute(
                """
                INSERT INTO moysklad_sync_logs (job_id, level, stage, entity_type, external_href, message, payload_excerpt_json)
                VALUES (?, 'info', 'diagnostic_mode', 'assortment', ?, ?, ?)
                """,
                (
                    job_id,
                    settings["source_product_folder_href"],
                    "Diagnostic mode: folder candidates, stock report rows, matching and DB writes",
                    json.dumps(diagnostic_payload, ensure_ascii=False),
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
