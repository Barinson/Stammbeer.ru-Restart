from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app.config import Settings, load_settings
from app.integrations.moysklad.client import MoyskladClient
from app.integrations.moysklad.settings_service import get_settings, save_settings, serialize_settings
from app.main import StammApp, admin_stats
from app.modules.catalog.service import public_catalog
from app.modules.public_views import business_storefront_page
from app.modules.auth.service import authenticate, change_password, create_session, current_user


class CoreFoundationTest(unittest.TestCase):

    def add_catalog_item(self, app: StammApp, name: str, container_type: str, slug: str) -> int:
        cursor = app.conn.execute(
            """
            INSERT INTO products (accounting_name, article)
            VALUES (?, ?)
            """,
            (name, slug.upper()),
        )
        product_id = cursor.lastrowid
        app.conn.execute(
            """
            INSERT INTO product_overrides (product_id, short_description, is_published)
            VALUES (?, ?, 1)
            """,
            (product_id, f"{name} для B2B-партнёров"),
        )
        app.conn.execute(
            """
            INSERT INTO business_catalog_items (
                product_id, slug, public_name, price_minor, currency, container_type,
                volume_liters, availability_status, sort_order, search_text, last_catalog_sync_at
            ) VALUES (?, ?, ?, 12300, 'RUB', ?, 30, 'available', 10, ?, '2026-06-01T08:00:00Z')
            """,
            (product_id, slug, name, container_type, name),
        )
        app.conn.commit()
        return product_id

    def make_app(self) -> StammApp:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db_path = Path(tmp.name) / "test.sqlite3"
        settings = Settings(
            app_name="test",
            env="test",
            host="127.0.0.1",
            port=0,
            database_url=str(db_path),
            session_secret="test-secret",
            admin_email="admin",
            admin_password="1",
            moysklad_api_base_url="https://api.moysklad.ru/api/remap/1.2",
        )
        return StammApp(settings)

    def test_migrations_seed_admin_and_core_tables(self) -> None:
        app = self.make_app()
        tables = {row[0] for row in app.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("users", tables)
        self.assertIn("moysklad_sync_settings", tables)
        self.assertIn("products", tables)
        self.assertIn("business_catalog_items", tables)
        self.assertIn("b2b_orders", tables)
        self.assertEqual(admin_stats(app.conn)["Статус sync"], "foundation ready")

    def test_admin_auth_session(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        self.assertIsNotNone(user)
        session_id = create_session(app.conn, user["id"])
        loaded = current_user(app.conn, f"stamm_admin_session={session_id}")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["email"], "admin")

    def test_default_local_admin_credentials_are_simple(self) -> None:
        settings = load_settings()
        self.assertEqual(settings.admin_email, "admin")
        self.assertEqual(settings.admin_password, "1")

    def test_admin_password_change_replaces_old_password(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        self.assertIsNotNone(user)
        ok, message = change_password(app.conn, user["id"], "1", "new-local-password")
        self.assertTrue(ok, message)
        self.assertIsNone(authenticate(app.conn, "admin", "1"))
        self.assertIsNotNone(authenticate(app.conn, "admin", "new-local-password"))


    def test_public_catalog_reads_local_read_model_and_filters(self) -> None:
        app = self.make_app()
        self.add_catalog_item(app, "Stamm IPA Keg", "keg", "stamm-ipa-keg")
        self.add_catalog_item(app, "Stamm Pale Ale Can", "can", "stamm-pale-ale-can")

        all_items = public_catalog(app.conn)
        self.assertEqual(all_items["meta"]["source"], "local_read_model")
        self.assertEqual(all_items["meta"]["totalLocalItems"], 2)
        self.assertEqual(len(all_items["items"]), 2)

        kegs = public_catalog(app.conn, "keg")
        self.assertEqual(len(kegs["items"]), 1)
        self.assertEqual(kegs["items"][0]["containerType"], "keg")

        cans = public_catalog(app.conn, "can")
        self.assertEqual(len(cans["items"]), 1)
        self.assertEqual(cans["items"][0]["containerType"], "can")

    def test_public_storefront_page_has_local_api_loading_and_empty_states(self) -> None:
        html = business_storefront_page()
        self.assertIn("/api/public/business/catalog", html)
        self.assertIn("Загружаем каталог", html)
        self.assertIn("Каталог скоро появится", html)
        self.assertIn("Ничего не найдено", html)
        self.assertIn("Не удалось загрузить каталог сайта", html)
        self.assertIn("data-filter=\"keg\"", html)
        self.assertIn("data-filter=\"can\"", html)
        self.assertNotIn("api.moysklad.ru", html)

    def test_public_catalog_api_endpoint_returns_local_data(self) -> None:
        app = self.make_app()
        self.add_catalog_item(app, "Stamm IPA Keg", "keg", "stamm-ipa-keg")
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/api/public/business/catalog?containerType=keg"
        payload = urllib.request.urlopen(url, timeout=5).read().decode("utf-8")
        data = json.loads(payload)
        self.assertEqual(data["meta"]["source"], "local_read_model")
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["name"], "Stamm IPA Keg")

    def test_moysklad_settings_are_saved_masked_and_serialized(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "secret-token-1234",
                "source_product_folder_href": "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/folder-id",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            user["id"],
        )
        settings = serialize_settings(get_settings(app.conn))
        self.assertTrue(settings["hasToken"])
        self.assertEqual(settings["tokenMasked"], "••••1234")
        self.assertTrue(settings["includeChildFolders"])
        self.assertTrue(settings["isEnabled"])

    def test_moysklad_source_folder_href_guard(self) -> None:
        client = MoyskladClient("token", api_base_url="https://api.moysklad.ru/api/remap/1.2")
        with self.assertRaises(ValueError):
            client.fetch_source_folder("https://example.test/entity/productfolder/1")


if __name__ == "__main__":
    unittest.main()
