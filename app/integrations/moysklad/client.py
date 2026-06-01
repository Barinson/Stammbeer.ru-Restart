from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_API_BASE_URL = "https://api.moysklad.ru/api/remap/1.2"


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

    def _request(self, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.api_base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json;charset=utf-8",
                "Content-Type": "application/json;charset=utf-8",
                "User-Agent": "StammBrewingCore/0.1",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = response.read().decode("utf-8")
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

    def fetch_product_folders(self, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._request("entity/productfolder", {"limit": limit, "offset": offset})

    def fetch_source_folder(self, source_folder_href: str) -> dict[str, Any]:
        if not source_folder_href.startswith(self.api_base_url):
            raise ValueError("source_folder_href must belong to configured MoySklad API base URL")
        path = source_folder_href.replace(f"{self.api_base_url}/", "", 1)
        return self._request(path)
