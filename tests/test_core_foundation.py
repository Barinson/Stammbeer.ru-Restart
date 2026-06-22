from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import Settings
from app.integrations.moysklad.client import MoyskladClient
from app.integrations.moysklad.settings_service import get_settings, save_settings, serialize_settings
from app.main import StammApp, admin_stats, parse_form
from app.modules.admin.views import render_cms_text
from app.modules.auth.service import authenticate, create_session, current_user


class CoreFoundationTest(unittest.TestCase):
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
            admin_email="admin@example.test",
            admin_password="correct horse battery staple",
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
        user = authenticate(app.conn, "admin@example.test", "correct horse battery staple")
        self.assertIsNotNone(user)
        session_id = create_session(app.conn, user["id"])
        loaded = current_user(app.conn, f"stamm_admin_session={session_id}")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["email"], "admin@example.test")

    def test_form_parsing_preserves_admin_line_breaks(self) -> None:
        form = parse_form("body=Строка+1%0D%0AСтрока+2%0AСтрока+3".encode("utf-8"))
        self.assertEqual(form["body"], "Строка 1\r\nСтрока 2\nСтрока 3")

    def test_cms_text_renderer_is_safe_and_preserves_line_breaks(self) -> None:
        rendered = render_cms_text("Строка 1\n<script>alert(1)</script>\nСтрока 3")
        self.assertIn('class="cms-text"', rendered)
        self.assertIn("Строка 1\n", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<script>", rendered)

    def test_moysklad_settings_are_saved_masked_and_serialized(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin@example.test", "correct horse battery staple")
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
