from __future__ import annotations

import base64
import json
import sqlite3
from typing import Any

from app.integrations.moysklad.client import DEFAULT_API_BASE_URL, MoyskladClient, MoyskladConnectionResult

# Foundation-only reversible encoding placeholder. Replace with KMS/libsodium before production.
def encode_token(token: str) -> str:
    return base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii")


def decode_token(encoded: str | None) -> str:
    if not encoded:
        return ""
    return base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")


def token_hint(token: str) -> str | None:
    if not token:
        return None
    return token[-4:].rjust(8, "•")


def get_settings(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM moysklad_sync_settings WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO moysklad_sync_settings (id, api_base_url, include_child_folders)
            VALUES (1, ?, 1)
            """,
            (DEFAULT_API_BASE_URL,),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM moysklad_sync_settings WHERE id = 1").fetchone()
    return row


def serialize_settings(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "apiBaseUrl": row["api_base_url"],
        "tokenMasked": row["token_hint"],
        "hasToken": bool(row["encrypted_token"]),
        "sourceProductFolderHref": row["source_product_folder_href"],
        "includeChildFolders": bool(row["include_child_folders"]),
        "storeExternalIds": json.loads(row["store_external_ids_json"] or "[]"),
        "priceTypeExternalId": row["price_type_external_id"],
        "fullSyncIntervalMinutes": row["full_sync_interval_minutes"],
        "stockSyncIntervalMinutes": row["stock_sync_interval_minutes"],
        "isEnabled": bool(row["is_enabled"]),
        "lastSuccessAt": row["last_success_at"],
        "lastErrorAt": row["last_error_at"],
    }


def save_settings(conn: sqlite3.Connection, data: dict[str, Any], user_id: int | None) -> None:
    current = get_settings(conn)
    token = data.get("token", "")
    encrypted_token = current["encrypted_token"]
    hint = current["token_hint"]
    if token:
        encrypted_token = encode_token(token)
        hint = token_hint(token)
    conn.execute(
        """
        UPDATE moysklad_sync_settings
        SET api_base_url = ?, encrypted_token = ?, token_hint = ?, source_product_folder_href = ?,
            include_child_folders = ?, full_sync_interval_minutes = ?, stock_sync_interval_minutes = ?,
            is_enabled = ?, updated_by_user_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (
            data.get("api_base_url") or DEFAULT_API_BASE_URL,
            encrypted_token,
            hint,
            data.get("source_product_folder_href") or None,
            1 if data.get("include_child_folders") else 0,
            int(data.get("full_sync_interval_minutes") or 360),
            int(data.get("stock_sync_interval_minutes") or 120),
            1 if data.get("is_enabled") else 0,
            user_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO audit_events (actor_user_id, action, entity_type, entity_id, after_json)
        VALUES (?, 'moysklad.settings.update', 'moysklad_sync_settings', '1', ?)
        """,
        (user_id, json.dumps({k: v for k, v in data.items() if k != "token"}, ensure_ascii=False)),
    )
    conn.commit()


def test_saved_connection(conn: sqlite3.Connection) -> MoyskladConnectionResult:
    settings = get_settings(conn)
    token = decode_token(settings["encrypted_token"])
    client = MoyskladClient(token=token, api_base_url=settings["api_base_url"])
    return client.test_connection()
