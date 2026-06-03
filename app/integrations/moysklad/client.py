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
        return self._fetch_collection_rows(
            "report/stock/all",
            query={
                "filter": f"store={store_href};quantityMode=positiveOnly",
                "groupBy": "variant",
            },
        )

    def fetch_source_folder(self, source_folder_href: str) -> dict[str, Any]:
        if not source_folder_href.startswith(self.api_base_url):
            raise ValueError("source_folder_href must belong to configured MoySklad API base URL")
        path = source_folder_href.replace(f"{self.api_base_url}/", "", 1)
        return self._request(path)
