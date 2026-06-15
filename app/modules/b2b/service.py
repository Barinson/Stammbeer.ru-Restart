from __future__ import annotations

import json
import sqlite3
import urllib.error
from typing import Any

from app.integrations.moysklad.client import MoyskladClient, normalize_api_reference
from app.integrations.moysklad.settings_service import decode_token, get_settings, load_json_array

B2B_STORE_NAME = "Склад готовой продукции"


def _meta(href: str, entity_type: str) -> dict[str, Any]:
    return {"meta": {"href": href, "type": entity_type, "mediaType": "application/json"}}


def _assortment_type(href: str) -> str:
    clean = href.split("?", 1)[0].rstrip("/")
    parts = clean.split("/")
    if "entity" in parts:
        index = parts.index("entity")
        if len(parts) > index + 1:
            return parts[index + 1]
    return "product"


def _selected_b2b_store(settings: sqlite3.Row, client: MoyskladClient) -> dict[str, Any]:
    stores = load_json_array(settings["available_stores_json"])
    if not stores:
        stores = client.fetch_stores()
    for store in stores:
        if str(store.get("name") or "").strip().lower() == B2B_STORE_NAME.lower():
            return store
    if settings["store_href"] and str(settings["store_name"] or "").strip().lower() == B2B_STORE_NAME.lower():
        return {
            "id": settings["store_id"],
            "href": settings["store_href"],
            "name": settings["store_name"] or settings["store_href"],
            "meta": {"href": settings["store_href"]},
        }
    raise ValueError(f"Не выбран склад для B2B-заказов. Нужен именно склад «{B2B_STORE_NAME}».")


def _default_organization(client: MoyskladClient) -> dict[str, Any]:
    organizations = client.fetch_organizations()
    if not organizations:
        raise ValueError("В МойСклад не найдена организация для создания заказа покупателя.")
    return organizations[0]


def build_customer_order_payload(
    order_number: str,
    customer: sqlite3.Row,
    order_items: list[dict[str, Any]],
    store: dict[str, Any],
    organization: dict[str, Any],
) -> dict[str, Any]:
    positions = []
    for entry in order_items:
        item = entry["item"]
        price = item.get("price") or {}
        assortment_href = item.get("externalHref")
        if not assortment_href:
            raise ValueError(f"У товара «{item['name']}» нет ссылки на номенклатуру МойСклад.")
        quantity = entry["quantity"]
        positions.append(
            {
                "quantity": quantity,
                "price": int(price.get("amountMinor") or 0),
                "reserve": quantity,
                "discount": 0,
                "vat": 0,
                "assortment": _meta(str(assortment_href), _assortment_type(str(assortment_href))),
            }
        )
    return {
        "name": order_number,
        "applicable": True,
        "description": f"B2B-заказ с сайта Stamm Brewing {order_number}",
        "organization": _meta(str(organization["href"]), "organization"),
        "agent": _meta(str(customer["counterparty_href"]), "counterparty"),
        "store": _meta(str(store["href"]), "store"),
        "positions": positions,
    }


def send_order_to_moysklad(
    conn: sqlite3.Connection,
    order_number: str,
    customer: sqlite3.Row,
    order_items: list[dict[str, Any]],
) -> dict[str, Any]:
    settings = get_settings(conn)
    token = decode_token(settings["encrypted_token"])
    if not token:
        raise ValueError("Не настроен токен МойСклад для отправки заказа.")
    if not customer["counterparty_href"]:
        raise ValueError("Аккаунт не связан с контрагентом МойСклад.")
    client = MoyskladClient(token=token, api_base_url=settings["api_base_url"])
    store = _selected_b2b_store(settings, client)
    organization = _default_organization(client)
    payload = build_customer_order_payload(order_number, customer, order_items, store, organization)
    try:
        response = client.create_customer_order(payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore") if hasattr(exc, "read") else ""
        raise ValueError(f"МойСклад отклонил заказ: HTTP {exc.code} {detail}".strip()) from exc
    reference = normalize_api_reference(response)
    return {
        "payload": payload,
        "response": response,
        "externalOrderId": reference.get("id"),
        "externalOrderHref": reference.get("href"),
        "store": store,
        "organization": organization,
    }
