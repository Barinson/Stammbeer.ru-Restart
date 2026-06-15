from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_API_BASE_URL = "https://api.moysklad.ru/api/remap/1.2"


def normalize_api_reference(row: dict[str, Any]) -> dict[str, Any]:
    href = (row.get("meta") or {}).get("href") or row.get("href") or ""
    return {
        "id": row.get("id") or href.rstrip("/").rsplit("/", 1)[-1],
        "href": href,
        "name": row.get("name") or href,
        "meta": row.get("meta") or {"href": href},
    }


DISCOUNT_VALUE_KEYS = (
    "personalDiscount",
    "salesDiscount",
    "discount",
    "discountPercent",
    "discountProcent",
    "discountPercentage",
    "percent",
    "value",
)


def _to_percent(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0.0, min(float(value), 100.0))
    except (TypeError, ValueError):
        return None


def _walk_discount_candidates(value: Any, path: str = "discounts") -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            candidates.extend(_walk_discount_candidates(item, f"{path}[{index}]"))
        return candidates
    if not isinstance(value, dict):
        return candidates
    for key, raw_value in value.items():
        next_path = f"{path}.{key}"
        if key in DISCOUNT_VALUE_KEYS:
            percent = _to_percent(raw_value)
            if percent is not None:
                candidates.append({"path": next_path, "value": percent})
        if isinstance(raw_value, (dict, list)):
            candidates.extend(_walk_discount_candidates(raw_value, next_path))
    return candidates


def _discount_like_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if "discount" in key.lower() or "скид" in key.lower()
    }


def price_type_diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    price_type = row.get("priceType") or {}
    reference = normalize_api_reference(price_type) if isinstance(price_type, dict) and price_type else None
    return {
        "rawPriceType": price_type,
        "priceTypeId": (reference or {}).get("id"),
        "priceTypeName": (reference or {}).get("name"),
        "priceTypeHref": (reference or {}).get("href"),
        "priceTypeMeta": (reference or {}).get("meta"),
    }


def discount_diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    discounts = row.get("discounts") or []
    discount_candidates = _walk_discount_candidates(discounts)
    all_candidates = _walk_discount_candidates(row, "counterparty")
    candidates = discount_candidates or all_candidates
    selected = candidates[0] if candidates else {"path": None, "value": 0.0}
    return {
        "counterpartyId": row.get("id"),
        "counterpartyName": row.get("name"),
        "counterpartyInn": row.get("inn"),
        "rawKeys": sorted(row.keys()),
        "rawDiscounts": discounts,
        "priceType": price_type_diagnostics(row),
        "discountLikeFields": _discount_like_fields(row),
        "candidates": candidates,
        "allCandidates": all_candidates,
        "selectedPath": selected.get("path"),
        "selectedValue": float(selected.get("value") or 0),
    }


def extract_personal_discount_percent(row: dict[str, Any]) -> float:
    return float(discount_diagnostics(row)["selectedValue"])


def normalize_counterparty(row: dict[str, Any]) -> dict[str, Any]:
    reference = normalize_api_reference(row)
    price_type = price_type_diagnostics(row)
    return {
        **reference,
        "inn": str(row.get("inn") or "").strip(),
        "legalTitle": row.get("legalTitle") or row.get("name") or reference["name"],
        "discountPercent": extract_personal_discount_percent(row),
        "discounts": row.get("discounts") or [],
        "priceType": price_type,
        "discountDiagnostics": discount_diagnostics(row),
    }


@dataclass(frozen=True)
class MoyskladConnectionResult:
    ok: bool
    status_code: int | None
    message: str
    account_name: str | None = None


class MoyskladClient:
    """Small server-side client for MoySklad JSON API 1.2.

    The client is intentionally used only by admin/integration services. Public
    storefront routes must continue to read local DB/read-model data only.
    """

    def __init__(self, token: str, api_base_url: str = DEFAULT_API_BASE_URL, timeout: int = 10):
        self.token = token.strip()
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self, has_body: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json;charset=utf-8",
            "Accept-Encoding": "gzip",
            "User-Agent": "StammBrewingCore/0.1",
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _decode_response(self, response: Any) -> str:
        raw_payload = response.read()
        content_encoding = ""
        if hasattr(response, "headers"):
            content_encoding = response.headers.get("Content-Encoding", "")
        if content_encoding.lower() == "gzip":
            raw_payload = gzip.decompress(raw_payload)
        return raw_payload.decode("utf-8")

    def _request(self, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
        request = urllib.request.Request(
            url,
            headers=self._headers(has_body=False),
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = self._decode_response(response)
            return json.loads(payload) if payload else {}

    def test_connection(self) -> MoyskladConnectionResult:
        if not self.token:
            return MoyskladConnectionResult(False, None, "Token is empty")
        try:
            payload = self._request("entity/organization", {"limit": 1})
            rows = payload.get("rows") or []
            account_name = rows[0].get("name") if rows else None
            return MoyskladConnectionResult(True, 200, "Connection successful", account_name)
        except urllib.error.HTTPError as exc:
            return MoyskladConnectionResult(False, exc.code, f"MoySklad HTTP error: {exc.code}")
        except urllib.error.URLError as exc:
            return MoyskladConnectionResult(False, None, f"MoySklad network error: {exc.reason}")
        except TimeoutError:
            return MoyskladConnectionResult(False, None, "MoySklad request timed out")
        except Exception as exc:  # defensive boundary for admin diagnostics
            return MoyskladConnectionResult(False, None, f"MoySklad check failed: {exc}")

    def _fetch_collection_rows(self, path: str, limit: int = 100, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        base_query = dict(query or {})
        while True:
            payload = self._request(path, {**base_query, "limit": limit, "offset": offset})
            page_rows = payload.get("rows") or []
            rows.extend(page_rows)
            if len(page_rows) < limit:
                break
            offset += limit
        return rows

    def find_counterparty_by_inn(self, inn: str) -> dict[str, Any] | None:
        normalized_inn = "".join(ch for ch in str(inn or "") if ch.isdigit())
        if not normalized_inn:
            return None
        rows = self._fetch_collection_rows(
            "entity/counterparty",
            limit=100,
            query={"filter": f"inn={normalized_inn}", "expand": "discounts.discount"},
        )
        for row in rows:
            counterparty = normalize_counterparty(row)
            if counterparty.get("inn") == normalized_inn:
                return counterparty
        return None

    def fetch_counterparty(self, counterparty_href: str) -> dict[str, Any]:
        if not counterparty_href.startswith(self.api_base_url):
            raise ValueError("counterparty_href must belong to configured MoySklad API base URL")
        path = counterparty_href.replace(f"{self.api_base_url}/", "", 1).split("?", 1)[0]
        return normalize_counterparty(self._request(path, {"expand": "discounts.discount"}))

    def fetch_stores(self) -> list[dict[str, Any]]:
        return [normalize_api_reference(row) for row in self._fetch_collection_rows("entity/store")]

    def fetch_product_folders(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._request("entity/productfolder", {"limit": limit, "offset": offset})

    def fetch_product_folder_options(self) -> list[dict[str, Any]]:
        return [normalize_api_reference(row) for row in self._fetch_collection_rows("entity/productfolder")]

    def fetch_product_folder_rows(self) -> list[dict[str, Any]]:
        return self._fetch_collection_rows("entity/productfolder")

    def fetch_assortment_rows(self) -> list[dict[str, Any]]:
        return self._fetch_collection_rows("entity/assortment")

    def fetch_stock_rows(self, store_href: str) -> list[dict[str, Any]]:
        # `report/stock/bystore` returns `stockByStore` for warehouses; the selected store is filtered locally
        # because the report filter is product/variant-oriented and `stockMode` is a top-level parameter.
        return self._fetch_collection_rows(
            "report/stock/bystore",
            query={
                "stockMode": "positiveOnly",
                "groupBy": "variant",
            },
        )

    def fetch_assortment_images(self, assortment_href: str) -> list[dict[str, Any]]:
        if not assortment_href.startswith(self.api_base_url):
            raise ValueError("assortment_href must belong to configured MoySklad API base URL")
        path = assortment_href.replace(f"{self.api_base_url}/", "", 1).split("?", 1)[0]
        return self._fetch_collection_rows(f"{path}/images")

    def fetch_source_folder(self, source_folder_href: str) -> dict[str, Any]:
        if not source_folder_href.startswith(self.api_base_url):
            raise ValueError("source_folder_href must belong to configured MoySklad API base URL")
        path = source_folder_href.replace(f"{self.api_base_url}/", "", 1)
        return self._request(path)
