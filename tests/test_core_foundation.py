from __future__ import annotations

import gzip
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app.config import Settings, load_settings
from app.db.migrations import ensure_compatibility_columns
from app.integrations.moysklad.auto_sync import auto_sync_status, compact_auto_sync_history, recover_stale_auto_sync_jobs, run_auto_catalog_sync_if_due
from app.integrations.moysklad.catalog_sync import extract_alcohol_percent, infer_container_type, latest_sync_diagnostics, run_manual_catalog_sync, utc_now_iso
from app.integrations.moysklad.client import MoyskladClient, normalize_counterparty
from app.modules.account.service import (
    DiscountRefreshError,
    authenticate_customer,
    change_customer_password,
    create_customer_session,
    current_customer,
    customer_session_from_cookie,
    list_customer_orders,
    register_customer,
)
from app.integrations.moysklad.settings_service import get_settings, refresh_integration_references, save_settings, serialize_settings
from app.modules.email import service as email_service
from app.main import StammApp, admin_b2b_orders, admin_stats
from app.modules.catalog.service import admin_catalog_items, assign_product_beer_style, beer_styles, public_catalog, publish_product, save_beer_style
from app.modules.content.service import get_public_site_content, save_public_content
from app.modules.admin.views import admin_catalog_page, b2b_orders_page
from app.modules import public_views as public_views_module
from app.modules.public_views import account_dashboard_page, account_login_page, beer_page, business_guest_page, business_storefront_page, contacts_page, gallery_page, home_page, maintenance_page
from app.modules.auth.service import authenticate, change_password, cookie_header, create_session, current_user
from app.timezone import format_moscow_datetime


class FakeMoyskladResponse:
    def __init__(self, payload: bytes, content_encoding: str | None = None):
        self._payload = payload
        self.headers = {}
        if content_encoding:
            self.headers["Content-Encoding"] = content_encoding

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_without_redirects(url: str):
    opener = urllib.request.build_opener(NoRedirect)
    try:
        return opener.open(url, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc


class CoreFoundationTest(unittest.TestCase):

    def add_catalog_item(self, app: StammApp, name: str, container_type: str, slug: str, image_url: str | None = None) -> int:
        cursor = app.conn.execute(
            """
            INSERT INTO products (accounting_name, article, stock_quantity, availability_status, sync_state, image_url)
            VALUES (?, ?, 10, 'available', 'active', ?)
            """,
            (name, slug.upper(), image_url),
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
                product_id, slug, public_name, image_url, price_minor, currency, container_type,
                volume_liters, availability_status, sort_order, search_text, last_catalog_sync_at
            ) VALUES (?, ?, ?, ?, 12300, 'RUB', ?, 30, 'available', 10, ?, '2026-06-01T08:00:00Z')
            """,
            (product_id, slug, name, image_url, container_type, name),
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
        self.assertIn("beer_styles", tables)
        self.assertIn("b2b_orders", tables)
        self.assertIn("customer_email_verification_tokens", tables)
        self.assertIn("customer_password_reset_tokens", tables)
        self.assertIn("email_send_logs", tables)
        self.assertIn("email_settings", tables)
        self.assertIn("email_templates", tables)
        self.assertEqual(admin_stats(app.conn)["Статус sync"], "foundation ready")

    def test_migrations_backfill_catalog_columns_for_legacy_databases(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                accounting_name TEXT NOT NULL
            );
            CREATE TABLE business_catalog_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                public_name TEXT NOT NULL
            );
            """
        )

        added = ensure_compatibility_columns(conn)
        product_columns = {row[1] for row in conn.execute("PRAGMA table_info(products)")}
        item_columns = {row[1] for row in conn.execute("PRAGMA table_info(business_catalog_items)")}

        self.assertIn("products.stock_quantity", added)
        self.assertIn("products.alcohol_percent", added)
        self.assertIn("business_catalog_items.price_type_prices_json", added)
        self.assertIn("business_catalog_items.alcohol_percent", added)
        self.assertIn("stock_quantity", product_columns)
        self.assertIn("price_type_prices_json", item_columns)

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


    def test_moscow_timezone_formatter_handles_utc_and_sqlite_timestamps(self) -> None:
        self.assertEqual(format_moscow_datetime("2026-07-04T10:00:00Z"), "04.07.2026 13:00 МСК")
        self.assertEqual(format_moscow_datetime("2026-07-04 10:00:00"), "04.07.2026 13:00 МСК")


    def test_admin_b2b_orders_page_lists_all_orders_with_numbers_comments_and_items(self) -> None:
        app = self.make_app()
        orders = [
            ("B2B-001", "sent_to_moysklad", "ООО Первый", "first@example.com", "Комментарий первого", 1200000, "order-ms-1", "https://example.test/order-ms-1", "2026-07-01T10:00:00Z"),
            ("B2B-002", "pending_moysklad", "ООО Второй", "second@example.com", "", 2400000, "", "", "2026-07-02T10:00:00Z"),
            ("B2B-003", "moysklad_error", "ООО Третий", "third@example.com", "Нужна доставка утром", 3600000, "", "", "2026-07-03T10:00:00Z"),
            ("B2B-004", "sent_to_moysklad", "ООО Четвёртый", "fourth@example.com", "Оставить у охраны", 4800000, "order-ms-4", "https://example.test/order-ms-4", "2026-07-04T10:00:00Z"),
        ]
        for index, order in enumerate(orders, start=1):
            order_id = app.conn.execute(
                """
                INSERT INTO b2b_orders (
                    number, status, contact_name, company_name, inn, email, phone, city, comment, total_minor,
                    currency, source_json, external_order_id, external_order_href, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '—', '—', ?, ?, 'RUB', '{}', ?, ?, ?, ?)
                """,
                (order[0], order[1], order[3], order[2], f"770000000{index}", order[3], order[4], order[5], order[6], order[7], order[8], order[8]),
            ).lastrowid
            app.conn.execute(
                """
                INSERT INTO b2b_order_items (order_id, product_id, quantity, price_minor, line_total_minor, product_snapshot_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (order_id, None, 12, 100000, 1200000, json.dumps({"name": f"Stamm позиция {index}"}, ensure_ascii=False)),
            )
        app.conn.commit()

        loaded_orders = admin_b2b_orders(app.conn)
        self.assertEqual(len(loaded_orders), 4)
        self.assertEqual(loaded_orders[0]["number"], "B2B-004")
        html = b2b_orders_page("admin@example.com", loaded_orders)
        self.assertIn("Всего B2B-заказов: 4", html)
        self.assertIn("B2B-001", html)
        self.assertIn("B2B-004", html)
        self.assertIn("04.07.2026 13:00 МСК", html)
        self.assertIn("Комментарий первого", html)
        self.assertIn("Комментарий не указан", html)
        self.assertIn("order-ms-4", html)
        self.assertIn("Stamm позиция 3", html)
        self.assertNotIn("Каркас раздела готов", html)

        admin = authenticate(app.conn, "admin", "1")
        admin_cookie = cookie_header(create_session(app.conn, admin["id"]))
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/admin/b2b-orders", headers={"Cookie": admin_cookie})
        response_html = urllib.request.urlopen(request, timeout=5).read().decode("utf-8")
        self.assertIn("B2B-заказы", response_html)
        self.assertIn("B2B-002", response_html)
        self.assertIn("02.07.2026 13:00 МСК", response_html)
        self.assertIn("Нужна доставка утром", response_html)
        self.assertIn("Состав заказа", response_html)


    def test_admin_customer_users_page_search_status_delete_and_password_reset(self) -> None:
        app = self.make_app()
        from app.modules.auth.security import hash_password

        customer_id = app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json,
                price_type_name, discount_percent, discount_source_json, email_verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', ?, 0, '{}', ?)
            """,
            (
                "partner-admin@example.com",
                hash_password("secret123"),
                "7701234567",
                "counterparty-admin",
                "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-admin",
                "ООО Админ Партнёр",
                "B2B 10%",
                "2026-06-01T00:00:00Z",
            ),
        ).lastrowid
        customer_session = create_customer_session(app.conn, customer_id)
        app.conn.execute(
            """
            INSERT INTO b2b_orders (
                number, status, contact_name, company_name, inn, email, phone, city, total_minor, source_json,
                customer_account_id, counterparty_href
            ) VALUES ('B2B-ADMIN', 'sent_to_moysklad', 'partner-admin@example.com', 'ООО Админ Партнёр',
                '7701234567', 'partner-admin@example.com', '—', '—', 1500000, '{}', ?,
                'https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-admin')
            """,
            (customer_id,),
        )
        app.conn.commit()

        admin = authenticate(app.conn, "admin", "1")
        admin_cookie = cookie_header(create_session(app.conn, admin["id"]))
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        users_request = urllib.request.Request(base + "/admin/users?q=7701234567", headers={"Cookie": admin_cookie})
        users_html = urllib.request.urlopen(users_request, timeout=5).read().decode("utf-8")
        self.assertIn("partner-admin@example.com", users_html)
        self.assertIn("ООО Админ Партнёр", users_html)
        self.assertIn("B2B 10%", users_html)
        self.assertIn("подтверждён", users_html)
        self.assertIn("Сброс", users_html)
        self.assertIn("/admin/users/create", users_html)
        self.assertIn("Временный пароль", users_html)
        self.assertIn("users-create-grid", users_html)
        self.assertIn("users-table", users_html)
        self.assertIn("Приостановить", users_html)
        self.assertIn("Удалить", users_html)

        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "token-123",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            admin["id"],
        )
        original_urlopen = urllib.request.urlopen

        def fake_urlopen(request, timeout=0):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if "api.moysklad.ru" not in url:
                return original_urlopen(request, timeout=timeout)
            rows = [] if "filter=inn%3D7700000000" in url else [
                {
                    "id": "counterparty-created",
                    "name": "ООО Новый Партнёр",
                    "inn": "7709998887",
                    "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-created"},
                }
            ]
            return FakeMoyskladResponse(json.dumps({"rows": rows}).encode("utf-8"))

        urllib.request.urlopen = fake_urlopen
        try:
            create_missing = urllib.request.Request(
                base + "/admin/users/create",
                data=urllib.parse.urlencode({"inn": "7700000000", "email": "missing-admin@example.com", "temporary_password": "secret123"}).encode("utf-8"),
                headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            missing_response = open_without_redirects(create_missing)
            self.assertEqual(missing_response.status, 303)
            self.assertIn("error=", missing_response.headers["Location"])
            self.assertIsNone(app.conn.execute("SELECT * FROM customer_accounts WHERE email = 'missing-admin@example.com'").fetchone())

            create_ok = urllib.request.Request(
                base + "/admin/users/create",
                data=urllib.parse.urlencode({"inn": "7709998887", "email": "created-admin@example.com", "temporary_password": "secret123"}).encode("utf-8"),
                headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            created_response = open_without_redirects(create_ok)
        finally:
            urllib.request.urlopen = original_urlopen
        self.assertEqual(created_response.status, 303)
        self.assertIn("result=", created_response.headers["Location"])
        created_account = authenticate_customer(app.conn, "created-admin@example.com", "secret123", refresh_discount=False)
        self.assertIsNotNone(created_account)
        self.assertEqual(created_account["counterparty_name"], "ООО Новый Партнёр")

        disable = urllib.request.Request(
            base + "/admin/users/status",
            data=urllib.parse.urlencode({"account_id": customer_id, "status": "suspended"}).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(disable).status, 303)
        self.assertIsNone(authenticate_customer(app.conn, "partner-admin@example.com", "secret123", refresh_discount=False))
        self.assertIsNone(current_customer(app.conn, f"stamm_customer_session={customer_session}"))

        activate = urllib.request.Request(
            base + "/admin/users/status",
            data=urllib.parse.urlencode({"account_id": customer_id, "status": "active"}).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(activate).status, 303)
        self.assertIsNotNone(authenticate_customer(app.conn, "partner-admin@example.com", "secret123", refresh_discount=False))

        reset = urllib.request.Request(
            base + "/admin/users/reset-password",
            data=urllib.parse.urlencode({"account_id": customer_id}).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(reset).status, 303)
        email_log = app.conn.execute("SELECT message_type, recipient_email, status FROM email_send_logs ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(email_log["message_type"], "password_reset")
        self.assertEqual(email_log["recipient_email"], "partner-admin@example.com")
        self.assertEqual(email_log["status"], "skipped")

        delete = urllib.request.Request(
            base + "/admin/users/delete",
            data=urllib.parse.urlencode({"account_id": customer_id, "confirm": "yes"}).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(delete).status, 303)
        account = app.conn.execute("SELECT status FROM customer_accounts WHERE id = ?", (customer_id,)).fetchone()
        self.assertIsNone(account)
        order = app.conn.execute("SELECT number, customer_account_id FROM b2b_orders WHERE number = 'B2B-ADMIN'").fetchone()
        self.assertIsNone(order["customer_account_id"])

        def fake_recreate_urlopen(request, timeout=0):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            if "api.moysklad.ru" not in url:
                return original_urlopen(request, timeout=timeout)
            return FakeMoyskladResponse(json.dumps({"rows": [{
                "id": "counterparty-admin",
                "name": "ООО Админ Партнёр",
                "inn": "7701234567",
                "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-admin"},
            }]}).encode("utf-8"))

        urllib.request.urlopen = fake_recreate_urlopen
        try:
            recreate = urllib.request.Request(
                base + "/admin/users/create",
                data=urllib.parse.urlencode({"inn": "7701234567", "email": "partner-admin@example.com", "temporary_password": "secret123"}).encode("utf-8"),
                headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            recreate_response = open_without_redirects(recreate)
        finally:
            urllib.request.urlopen = original_urlopen
        self.assertEqual(recreate_response.status, 303)
        self.assertIn("result=", recreate_response.headers["Location"])
        self.assertIsNotNone(authenticate_customer(app.conn, "partner-admin@example.com", "secret123", refresh_discount=False))


    def test_admin_email_management_page_settings_logs_and_manual_actions(self) -> None:
        app = self.make_app()
        from app.modules.auth.security import hash_password

        customer_id = app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json,
                price_type_name, discount_percent, discount_source_json, email_verified_at
            ) VALUES (?, ?, '7701112223', 'cp-mail', 'https://api.moysklad.ru/api/remap/1.2/entity/counterparty/cp-mail',
                'ООО Почтовый Тест', '{}', 'B2B', 0, '{}', NULL)
            """,
            ("mail-admin@example.com", hash_password("secret123")),
        ).lastrowid
        order_id = app.conn.execute(
            """
            INSERT INTO b2b_orders (
                number, status, contact_name, company_name, inn, email, phone, city, comment, total_minor,
                source_json, customer_account_id, counterparty_href
            ) VALUES ('B2B-MAIL', 'sent_to_moysklad', 'mail-admin@example.com', 'ООО Почтовый Тест',
                '7701112223', 'mail-admin@example.com', '—', '—', 'Комментарий', 2400000, '{}', ?,
                'https://api.moysklad.ru/api/remap/1.2/entity/counterparty/cp-mail')
            """,
            (customer_id,),
        ).lastrowid
        app.conn.execute(
            """
            INSERT INTO b2b_order_items (order_id, product_id, variant_id, quantity, price_minor, line_total_minor,
                product_snapshot_json, availability_snapshot_json)
            VALUES (?, NULL, NULL, 12, 200000, 2400000, '{"name":"Тестовый сорт"}', '{}')
            """,
            (order_id,),
        )
        app.conn.commit()

        sent_messages = []

        class FakeSMTP:
            def __init__(self, host, port, timeout=15):
                self.host = host
                self.port = port
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def starttls(self):
                return None

            def login(self, username, password):
                self.username = username
                self.password = password

            def send_message(self, message):
                sent_messages.append(message)

        old_ssl = email_service.smtplib.SMTP_SSL
        old_smtp = email_service.smtplib.SMTP
        email_service.smtplib.SMTP_SSL = FakeSMTP
        email_service.smtplib.SMTP = FakeSMTP
        self.addCleanup(lambda: setattr(email_service.smtplib, "SMTP_SSL", old_ssl))
        self.addCleanup(lambda: setattr(email_service.smtplib, "SMTP", old_smtp))

        admin = authenticate(app.conn, "admin", "1")
        admin_cookie = cookie_header(create_session(app.conn, admin["id"]))
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        email_request = urllib.request.Request(base + "/admin/email", headers={"Cookie": admin_cookie})
        email_html = urllib.request.urlopen(email_request, timeout=5).read().decode("utf-8")
        self.assertIn("Почта / Подключение", email_html)
        self.assertIn("Почта / Логи", email_html)
        self.assertIn("Почта / Ручные действия", email_html)
        self.assertIn("heading_order_created", email_html)
        self.assertIn("image_file_order_created", email_html)
        self.assertIn("background_image_enabled_order_created", email_html)

        save = urllib.request.Request(
            base + "/admin/email/settings",
            data=urllib.parse.urlencode({
                "provider": "yandex",
                "is_enabled": "on",
                "smtp_host": "smtp.yandex.com",
                "smtp_port": "465",
                "smtp_username": "mailer@example.com",
                "smtp_password": "app-secret",
                "from_email": "mailer@example.com",
                "from_name": "Stamm Mail",
                "reply_to_email": "reply@example.com",
                "use_ssl": "on",
            }).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(save).status, 303)
        stored = app.conn.execute("SELECT smtp_password_secret, from_name FROM email_settings WHERE id = 1").fetchone()
        self.assertEqual(stored["from_name"], "Stamm Mail")
        self.assertNotEqual(stored["smtp_password_secret"], "app-secret")

        probe = urllib.request.Request(base + "/admin/email/test-connection", data=b"", headers={"Cookie": admin_cookie}, method="POST")
        self.assertEqual(open_without_redirects(probe).status, 303)

        test_mail = urllib.request.Request(
            base + "/admin/email/send-test",
            data=urllib.parse.urlencode({"to_email": "qa@example.com", "message_type": "test"}).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(test_mail).status, 303)
        self.assertTrue(sent_messages)
        log = app.conn.execute("SELECT message_type, recipient_email, status, provider FROM email_send_logs ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(log["message_type"], "test")
        self.assertEqual(log["recipient_email"], "qa@example.com")
        self.assertEqual(log["status"], "sent")
        self.assertEqual(log["provider"], "yandex")

        templates = urllib.request.Request(
            base + "/admin/email/templates",
            data=urllib.parse.urlencode({
                "enabled_email_confirmation": "on",
                "subject_email_confirmation": "Confirm custom",
                "heading_email_confirmation": "Confirm heading",
                "enabled_password_reset": "on",
                "subject_password_reset": "Reset custom",
                "heading_password_reset": "Reset heading",
                "preheader_password_reset": "Reset preheader",
                "body_password_reset": "Reset managed body",
                "footer_password_reset": "Reset footer",
                "image_url_password_reset": "/media/reset-banner.jpg",
                "background_color_password_reset": "#123456",
                "background_image_url_password_reset": "/media/reset-bg.jpg",
                "background_image_enabled_password_reset": "on",
                "enabled_registration_confirmation": "on",
                "subject_registration_confirmation": "Registration custom",
                "enabled_order_created": "on",
                "subject_order_created": "Order custom",
                "heading_order_created": "Order heading",
                "enabled_order_status_changed": "on",
                "subject_order_status_changed": "Status custom",
                "enabled_test": "on",
                "subject_test": "Test custom",
            }).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(templates).status, 303)
        subject = app.conn.execute("SELECT subject FROM email_templates WHERE message_type = 'password_reset'").fetchone()["subject"]
        self.assertEqual(subject, "Reset custom")
        reset_template = app.conn.execute("SELECT heading, preheader_text, footer_text, image_url, background_color, background_image_url, background_image_enabled FROM email_templates WHERE message_type = 'password_reset'").fetchone()
        self.assertEqual(reset_template["heading"], "Reset heading")
        self.assertEqual(reset_template["preheader_text"], "Reset preheader")
        self.assertEqual(reset_template["footer_text"], "Reset footer")
        self.assertEqual(reset_template["image_url"], "/media/reset-banner.jpg")
        self.assertEqual(reset_template["background_color"], "#123456")
        self.assertEqual(reset_template["background_image_url"], "/media/reset-bg.jpg")
        self.assertEqual(reset_template["background_image_enabled"], 1)

        reset = urllib.request.Request(
            base + "/admin/email/manual-reset",
            data=urllib.parse.urlencode({"customer_ref": "mail-admin@example.com"}).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(reset).status, 303)
        reset_message = sent_messages[-1]
        reset_html = reset_message.get_payload()[1].get_content()
        self.assertIn("Reset heading", reset_html)
        self.assertIn("Reset managed body", reset_html)
        self.assertIn("/media/reset-banner.jpg", reset_html)
        self.assertIn("/media/reset-bg.jpg", reset_html)
        self.assertIn('class="email-shell"', reset_html)
        self.assertIn("color:#172625", reset_html)
        self.assertIn("font-size:15px;line-height:1.5", reset_html)
        self.assertIn("@media screen and (max-width:520px)", reset_html)
        self.assertIn(".email-body table { font-size:12px", reset_html)
        reset_text = reset_message.get_payload()[0].get_content()
        self.assertIn("Reset footer", reset_text)
        confirm = urllib.request.Request(
            base + "/admin/email/manual-confirmation",
            data=urllib.parse.urlencode({"customer_ref": str(customer_id)}).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(confirm).status, 303)
        order_mail = urllib.request.Request(
            base + "/admin/email/manual-order-created",
            data=urllib.parse.urlencode({"order_id": str(order_id)}).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(order_mail).status, 303)
        order_html = sent_messages[-1].get_payload()[1].get_content()
        self.assertIn("<table style='width:100%;border-collapse:collapse;color:#172625;font-size:14px;'>", order_html)
        self.assertIn("padding:7px 6px", order_html)
        message_types = [row["message_type"] for row in app.conn.execute("SELECT message_type FROM email_send_logs ORDER BY id")]
        self.assertIn("password_reset", message_types)
        self.assertIn("email_confirmation", message_types)
        self.assertIn("order_created", message_types)

        logs_request = urllib.request.Request(base + "/admin/email?status=sent&q=mail-admin", headers={"Cookie": admin_cookie})
        logs_html = urllib.request.urlopen(logs_request, timeout=5).read().decode("utf-8")
        self.assertIn("mail-admin@example.com", logs_html)
        self.assertIn("order_created", logs_html)

    def test_moysklad_counterparty_discount_diagnostics_supports_nested_discount_value(self) -> None:
        counterparty = normalize_counterparty(
            {
                "id": "counterparty-1",
                "name": "ООО Диагностика",
                "inn": "7701234567",
                "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1"},
                "discounts": [{"discount": {"name": "B2B", "discount": 10}}],
            }
        )
        self.assertEqual(counterparty["discountPercent"], 10)
        self.assertEqual(counterparty["discountDiagnostics"]["selectedPath"], "discounts[0].discount.discount")
        self.assertEqual(counterparty["discountDiagnostics"]["selectedValue"], 10)

    def test_moysklad_counterparty_discount_diagnostics_searches_discount_like_fields(self) -> None:
        counterparty = normalize_counterparty(
            {
                "id": "counterparty-2",
                "name": "ООО Поля скидки",
                "inn": "7701234567",
                "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-2"},
                "discounts": [],
                "salesDiscount": 9.5,
            }
        )
        self.assertEqual(counterparty["discountPercent"], 9.5)
        self.assertEqual(counterparty["discountDiagnostics"]["selectedPath"], "counterparty.salesDiscount")
        self.assertEqual(counterparty["discountDiagnostics"]["selectedValue"], 9.5)

    def test_moysklad_container_inference_treats_only_045_skus_as_cans(self) -> None:
        self.assertEqual(infer_container_type({"name": "Stamm Pale Ale 0,45 can", "article": "PALE-CAN"}), "can")
        self.assertEqual(infer_container_type({"name": "Stamm Lager 0.45 банка", "article": "LAGER-CAN"}), "can")
        self.assertEqual(infer_container_type({"name": "Stamm Lager 10л (S)", "article": "LAGER-S"}), "keg")
        self.assertEqual(infer_container_type({"name": "Stamm IPA 20л (A)", "code": "IPA-A"}), "keg")
        self.assertEqual(infer_container_type({"name": "Stamm IPA can", "code": "IPA-CAN"}), "keg")

    def test_public_content_settings_drive_home_and_navigation(self) -> None:
        app = self.make_app()
        save_public_content(
            app.conn,
            {
                "home_hero_title": "CUSTOM",
                "home_hero_subtitle": "GOLD",
                "home_logo_url": "/media/custom-logo.svg",
                "home_hero_title_size_px": "144",
                "home_hero_title_weight": "800",
                "home_hero_subtitle_size_px": "96",
                "home_hero_subtitle_weight": "700",
                "home_hero_line_gap_px": "18",
                "home_content_bg_url": "/media/taproom-bg.jpg",
                "home_news_title": "Fresh release",
                "home_news_text": "New lager batch is ready.",
                "home_news_image_url": "/media/news.jpg",
                "home_news_link_url": "/business/catalog",
                "home_news_link_label": "Order now",
                "site_public_base_url": "https://example.test",
                "site_title": "Stamm Test",
                "site_description": "Тестовое описание Stamm для поиска.",
                "site_favicon_url": "/media/favicon.svg",
                "site_og_image_url": "/media/og.jpg",
                "site_yandex_metrika_id": "110732851",
                "mobile_menu_icon_url": "/media/mobile-menu.svg",
                "business_min_order_amount_minor": "2500000",
                "business_guest_text": "Партнёрам — напишите на marketing@stammbeer.ru",
                "business_guest_font_size_px": "28",
                "business_guest_font_weight": "700",
                "age_gate_title": "Проверка возраста",
                "age_gate_text": "Вам уже исполнилось 18 лет?",
                "age_gate_title_font_size_px": "44",
                "age_gate_title_font_weight": "800",
                "age_gate_text_font_size_px": "20",
                "age_gate_text_font_weight": "600",
                "age_gate_confirm_label": "Да, можно",
                "age_gate_deny_label": "Нет",
                "maintenance_enabled": "1",
                "maintenance_text": "Сайт находится на технических работах, по всем вопросам пишите marketing@stammbeer.ru",
                "maintenance_font_size_px": "30",
                "maintenance_font_weight": "700",
                "maintenance_image_url": "/media/maintenance.png",
                "gallery_title": "Галерея Stamm",
                "gallery_description": "Производство\nи события",
                "gallery_section_0_title": "Пивоварня",
                "gallery_section_0_sort_order": "10",
                "gallery_section_0_visible": "1",
                "gallery_section_0_item_caption_0": "Варочный порядок",
                "gallery_section_0_item_image_url_0": "/media/gallery-brew.jpg",
                "gallery_section_0_item_size_0": "large",
                "gallery_section_0_item_sort_order_0": "20",
                "gallery_section_0_item_visible_0": "1",
                "gallery_section_1_title": "Скрытый блок",
                "gallery_section_1_sort_order": "20",
                "gallery_section_1_visible": "0",
                "gallery_section_1_item_caption_0": "Скрытое фото",
                "gallery_section_1_item_image_url_0": "/media/gallery-hidden.jpg",
                "gallery_section_1_item_size_0": "small",
                "gallery_section_1_item_sort_order_0": "10",
                "gallery_section_1_item_visible_0": "1",
                "gallery_item_caption_0": "Варочный порядок",
                "gallery_item_image_url_0": "/media/gallery-brew.jpg",
                "gallery_item_size_0": "large",
                "gallery_item_sort_order_0": "20",
                "gallery_item_visible_0": "1",
                "gallery_item_caption_1": "Скрытое фото",
                "gallery_item_image_url_1": "/media/gallery-hidden.jpg",
                "gallery_item_size_1": "small",
                "gallery_item_sort_order_1": "10",
                "gallery_item_visible_1": "0",
                "section_bg_home_url": "/media/bg-home.jpg",
                "section_bg_beer_url": "/media/bg-beer.jpg",
                "section_bg_business_url": "/media/bg-business.jpg",
                "section_bg_history_url": "/media/bg-gallery.jpg",
                "section_bg_contacts_url": "/media/bg-contacts.jpg",
                "section_bg_visit_url": "/media/bg-visit.jpg",
                "contact_email_label_0": "Основной",
                "contact_email_value_0": "hello@stamm.test",
                "contact_email_sort_order_0": "20",
                "contact_email_visible_0": "on",
                "contact_email_label_1": "Скрытый",
                "contact_email_value_1": "hidden@stamm.test",
                "contact_email_sort_order_1": "10",
                "contact_phone_label_0": "Офис",
                "contact_phone_value_0": "+7 999 111-22-33",
                "contact_phone_sort_order_0": "10",
                "contact_phone_visible_0": "on",
                "contacts_address": "Москва, тестовый завод\nстроение 2",
                "contacts_address_color": "#C7B166",
                "contacts_description": "Контакты производства Stamm",
                "contacts_description_color": "#F6F1E3",
                "contacts_map_lat": "55.7001",
                "contacts_map_lng": "37.6002",
                "contacts_map_zoom": "15",
                "contacts_map_height_px": "280",
                "contacts_map_width_px": "360",
                "contacts_map_title": "Stamm Test Brewery",
                "typography_nav_font_size_px": "18",
                "typography_page_title_font_size_px": "52",
                "typography_body_font_size_px": "17",
                "typography_contact_text_font_size_px": "21",
                "typography_product_title_font_size_px": "19",
                "typography_price_font_size_px": "23",
                "typography_cart_font_size_px": "15",
                "menu_beer_label": "Beer list",
                "menu_beer_sort_order": "10",
                "menu_beer_visible": "on",
                "menu_visit_label": "Visit",
                "menu_visit_sort_order": "20",
                "menu_visit_visible": "on",
                "menu_history_label": "Story",
                "menu_history_sort_order": "30",
                "menu_history_visible": "on",
                "menu_business_label": "Partners",
                "menu_business_sort_order": "40",
                "menu_business_visible": "on",
                "menu_contacts_label": "Contacts",
                "menu_contacts_sort_order": "50",
                "menu_contacts_visible": "on",
                "action_tg_label": "TG",
                "action_tg_href": "https://t.me/stamm",
                "action_tg_sort_order": "10",
                "action_tg_visible": "on",
                "action_vk_label": "VK",
                "action_vk_href": "https://vk.com/stamm",
                "action_vk_sort_order": "20",
                "action_vk_visible": "on",
                "action_untappd_label": "Untappd",
                "action_untappd_href": "https://untappd.com/stamm",
                "action_untappd_icon_url": "/media/untappd.svg",
                "action_untappd_sort_order": "30",
                "action_untappd_visible": "on",
                "action_cart_label": "Корзина",
                "action_cart_href": "/business#cart",
                "action_cart_sort_order": "40",
                "action_cart_visible": "on",
                "action_account_label": "Личный кабинет",
                "action_account_href": "/account",
                "action_account_sort_order": "50",
                "action_account_visible": "on",
            },
        )
        content = get_public_site_content(app.conn)
        self.assertEqual(content["site"]["site_public_base_url"], "https://example.test")
        self.assertEqual(content["site"]["site_favicon_url"], "/media/favicon.svg")
        self.assertEqual(content["business"]["business_min_order_amount_minor"], "2500000")
        self.assertEqual(content["business"]["business_guest_text"], "Партнёрам — напишите на marketing@stammbeer.ru")
        self.assertEqual(content["business"]["business_guest_font_size_px"], "28")
        self.assertEqual(content["business"]["business_guest_font_weight"], "700")
        self.assertEqual(content["site"]["age_gate_title"], "Проверка возраста")
        self.assertEqual(content["site"]["age_gate_text_font_size_px"], "20")
        self.assertEqual(content["site"]["maintenance_enabled"], "1")
        self.assertEqual(content["site"]["maintenance_image_url"], "/media/maintenance.png")
        self.assertEqual(content["contacts"]["emails"][0]["value"], "hidden@stamm.test")
        self.assertFalse(content["contacts"]["emails"][0]["is_visible"])
        self.assertEqual(content["contacts"]["emails"][1]["value"], "hello@stamm.test")
        self.assertTrue(content["contacts"]["emails"][1]["is_visible"])
        self.assertEqual(content["contacts"]["phones"][0]["label"], "Офис")
        contacts_html = contacts_page(content)
        self.assertIn("hello@stamm.test", contacts_html)
        self.assertNotIn("hidden@stamm.test", contacts_html)
        self.assertIn("+7 999 111-22-33", contacts_html)
        self.assertIn("Москва, тестовый завод\nстроение 2", contacts_html)
        self.assertIn("color:#F6F1E3", contacts_html)
        self.assertIn("<span>Адрес</span>", contacts_html)
        self.assertNotIn("map-info", contacts_html)
        self.assertNotIn("map-compact-badge", contacts_html)
        self.assertNotIn("оценка на Яндекс Картах", contacts_html)
        self.assertNotIn("Stamm Brewing★ оценка на Яндекс Картах", contacts_html)
        self.assertIn("display:block; line-height:0", contacts_html)
        self.assertIn("contacts-info-card", contacts_html)
        self.assertNotIn("<h1>Контакты</h1>", contacts_html)
        self.assertIn("grid-template-columns:1fr", contacts_html)
        self.assertIn("justify-self:center", contacts_html)
        self.assertIn("mode=search", contacts_html)
        self.assertIn("text=Stamm%20Test%20Brewery", contacts_html)
        self.assertIn("font-weight:500; white-space:pre-line", contacts_html)
        self.assertIn("min-height:180px; max-height:420px", contacts_html)
        self.assertIn("Stamm Test Brewery", contacts_html)
        self.assertIn("--contacts-map-height:280px; --contacts-map-width:360px", contacts_html)
        self.assertIn("width:min(100%, var(--contacts-map-width))", contacts_html)
        self.assertIn("yandex.ru/map-widget", contacts_html)
        self.assertIn("55.7001", contacts_html)
        self.assertIn("37.6002", contacts_html)
        self.assertIn("--stamm-page-title-font-size:52px", contacts_html)
        self.assertIn("--stamm-contact-text-font-size:21px", contacts_html)
        self.assertNotIn("map-caption", contacts_html)
        html = home_page(content)
        self.assertIn("CUSTOM", html)
        self.assertIn('<meta name="description" content="Stamm Brewing: крафтовая пивоварня, новости, партнёры и контакты.">', html)
        self.assertIn('<meta name="robots" content="index,follow">', html)
        self.assertIn('<link rel="canonical" href="https://example.test/">', html)
        self.assertIn('<link rel="icon" type="image/svg+xml" href="/favicon.svg">', html)
        self.assertEqual(html.count("mc.yandex.ru/metrika/tag.js?id=110732851"), 1)
        self.assertIn("ym(110732851, 'init'", html)
        self.assertIn('ecommerce:"dataLayer"', html)
        self.assertIn("window.dataLayer = window.dataLayer || [];", html)
        self.assertIn('<meta property="og:title" content="Stamm Brewing — крафтовая пивоварня">', html)
        self.assertIn('<meta property="og:image" content="https://example.test/media/og.jpg">', html)
        self.assertIn('"@type":"BreadcrumbList"', html)
        self.assertIn('"name":"Главная","item":"https://example.test/"', html)
        self.assertIn("GOLD", html)
        self.assertIn("/media/custom-logo.svg", html)
        self.assertIn("Fresh release", html)
        self.assertIn("New lager batch is ready.", html)
        self.assertIn("/media/news.jpg", html)
        self.assertIn("/business/catalog", html)
        self.assertIn("Order now", html)
        self.assertNotIn('aria-label="Корзина"', html)
        self.assertNotIn('/business#cart', html)
        self.assertIn("/media/bg-home.jpg", html)
        self.assertIn("--section-bg:url('/media/bg-home.jpg')", html)
        self.assertIn("background-attachment:fixed", html)
        self.assertIn("linear-gradient(180deg, rgba(16,88,89,.84)", html)
        self.assertIn("min-height:100vh", html)
        self.assertIn("position:fixed", html)
        self.assertIn("max-width:154px", html)
        self.assertIn("--home-title-size:144px", html)
        self.assertIn("--home-title-weight:800", html)
        self.assertIn("--home-subtitle-size:96px", html)
        self.assertIn("--home-subtitle-weight:700", html)
        self.assertIn("--home-line-gap:18px", html)
        self.assertIn("--stamm-nav-font-size:18px", html)
        self.assertIn("--stamm-body-font-size:17px", html)
        self.assertIn("news-card__image-link", html)
        self.assertIn(".news-card { width:min(1120px,100%);", html)
        self.assertIn("background:transparent; border:0; border-radius:0; padding:0; box-shadow:none", html)
        self.assertIn("gap:clamp(34px,4vw,64px)", html)
        self.assertIn(".nav-icon { width:32px; height:32px; border:0; border-radius:999px", html)
        self.assertIn("@media (max-width:920px)", html)
        self.assertIn("--mobile-menu-offset:112px", html)
        self.assertIn("body > main { padding-top:var(--menu-offset,176px) !important", html)
        self.assertIn("padding-top:var(--menu-offset,176px) !important", html)
        self.assertIn("body > main { padding-top:var(--menu-mobile-offset,var(--mobile-menu-offset)) !important", html)
        self.assertIn("padding-top:var(--menu-mobile-offset,var(--mobile-menu-offset)) !important", html)
        self.assertIn(".top-nav { position:fixed; align-items:center; flex-direction:row; flex-wrap:wrap", html)
        self.assertIn("backdrop-filter:blur(6px)", html)
        self.assertIn(".nav-links a { flex:1 1 max-content; min-width:max-content; text-align:center; }", html)
        self.assertIn("mobile-menu-toggle", html)
        self.assertIn('class="mobile-menu-toggle mobile-menu-toggle--image"', html)
        self.assertIn('/media/mobile-menu.svg', html)
        self.assertIn('aria-controls="mobileNavDrawer"', html)
        self.assertIn('id="mobileNavDrawer"', html)
        self.assertIn("mobile-drawer__links", html)
        self.assertIn("width:min(64vw,220px)", html)
        self.assertIn(".top-nav { display:grid; grid-template-columns:34px minmax(0,1fr) auto", html)
        self.assertIn(".nav-links { display:none; }", html)
        self.assertIn('document.body.classList.toggle("mobile-nav-open", isOpen)', html)
        self.assertIn(".nav-icon { width:26px; height:26px; }", html)
        self.assertIn(".home-subtitle { font-size:clamp(18px,6vw,26px); letter-spacing:.14em; }", html)
        self.assertIn(".home-content { background-size:cover, cover; background-position:center, center; background-attachment:scroll, fixed; }", html)
        self.assertIn("background:var(--golden-malt); color:var(--ink)", html)
        self.assertIn(".nav-icon img { width:100%; height:100%; padding:0; object-fit:contain", html)
        self.assertNotIn("nav-icon--cart", html)
        self.assertNotIn("news-card__label", html)
        self.assertNotIn("news-card__cta", html)
        self.assertIn("Beer list", html)
        self.assertIn("https://untappd.com/stamm", html)
        self.assertIn("/media/untappd.svg", html)
        self.assertIn("Проверка возраста", html)
        self.assertIn("Вам уже исполнилось 18 лет?", html)
        self.assertIn("Да, можно", html)
        self.assertIn("Нет", html)
        self.assertIn("window.history.back()", html)
        self.assertIn("about:blank", html)
        self.assertIn("stamm_age_confirmed_session", html)
        self.assertIn("--age-gate-title-size:44px", html)
        self.assertIn("--age-gate-title-weight:800", html)
        self.assertIn("--age-gate-text-size:20px", html)
        self.assertIn("--age-gate-text-weight:600", html)
        html_for_customer = home_page({**content, "viewer": {"is_customer": True}})
        self.assertIn('aria-label="Корзина"', html_for_customer)
        self.assertIn('/business#cart', html_for_customer)
        self.assertNotIn("ageGate", html_for_customer)
        guest_html = business_guest_page(content)
        self.assertIn('<link rel="icon" type="image/svg+xml" href="/favicon.svg">', guest_html)
        self.assertEqual(guest_html.count("mc.yandex.ru/metrika/tag.js?id=110732851"), 1)
        self.assertEqual(business_storefront_page({**content, "viewer": {"is_customer": True}}).count("mc.yandex.ru/metrika/tag.js?id=110732851"), 1)
        self.assertEqual(beer_page(content).count("mc.yandex.ru/metrika/tag.js?id=110732851"), 1)
        self.assertEqual(gallery_page(content).count("mc.yandex.ru/metrika/tag.js?id=110732851"), 1)
        self.assertEqual(contacts_page(content).count("mc.yandex.ru/metrika/tag.js?id=110732851"), 1)
        self.assertNotIn("mc.yandex.ru/metrika/tag.js", home_page({**content, "site": {**content["site"], "site_yandex_metrika_id": ""}}))
        self.assertIn('"name":"Бизнес","item":"https://example.test/business"', guest_html)
        self.assertIn("Партнёрам — напишите на marketing@stammbeer.ru", guest_html)
        self.assertIn("min-height:100vh", guest_html)
        self.assertIn("--business-guest-font-size:28px", guest_html)
        self.assertIn("--business-guest-font-weight:700", guest_html)
        self.assertIn("--section-bg:url('/media/bg-business.jpg')", guest_html)
        self.assertIn("background-size:auto, cover, cover", guest_html)
        self.assertIn("background-attachment:scroll, fixed, fixed", guest_html)
        self.assertIn("font-size:min(var(--business-guest-font-size), 22px)", guest_html)
        maintenance_html = maintenance_page(content)
        self.assertIn("Технические работы", maintenance_html)
        self.assertIn("mailto:marketing@stammbeer.ru", maintenance_html)
        self.assertIn("/media/maintenance.png", maintenance_html)
        self.assertIn("--maintenance-font-size:30px", maintenance_html)
        self.assertIn("--maintenance-font-weight:700", maintenance_html)
        self.assertEqual(content["gallery"]["gallery_title"], "Галерея Stamm")
        gallery_html = gallery_page(content)
        self.assertIn('<link rel="icon" type="image/svg+xml" href="/favicon.svg">', gallery_html)
        self.assertIn('"name":"Галерея","item":"https://example.test/gallery"', gallery_html)
        self.assertIn("Галерея Stamm", gallery_html)
        self.assertIn("Производство\nи события", gallery_html)
        self.assertIn("Пивоварня", gallery_html)
        self.assertNotIn("Скрытый блок", gallery_html)
        self.assertIn("/media/gallery-brew.jpg", gallery_html)
        self.assertIn("gallery-section", gallery_html)
        self.assertIn("gallery-card--large", gallery_html)
        self.assertIn('"name":"Контакты","item":"https://example.test/contacts"', contacts_html)
        self.assertIn('<link rel="icon" type="image/svg+xml" href="/favicon.svg">', contacts_html)
        self.assertIn('<link rel="icon" type="image/svg+xml" href="/favicon.svg">', account_login_page(content))
        self.assertIn("data-gallery-open", gallery_html)
        self.assertIn("galleryLightbox", gallery_html)
        self.assertIn("filter:brightness(1.08) saturate(1.02)", gallery_html)
        self.assertIn("rgba(0,0,0,.42)", gallery_html)
        self.assertIn("--section-bg:url('/media/bg-gallery.jpg')", gallery_html)
        self.assertIn(".gallery-card { min-height:220px; border-radius:20px; }", gallery_html)
        self.assertNotIn("rgba(11,63,64,.78)", gallery_html)
        self.assertNotIn("/media/gallery-hidden.jpg", gallery_html)

    def test_maintenance_page_uses_safe_fallbacks_with_incomplete_defaults(self) -> None:
        original_defaults = dict(public_views_module.SITE_DEFAULTS)
        try:
            for key in (
                "maintenance_font_size_px",
                "maintenance_font_weight",
                "maintenance_text",
                "maintenance_image_url",
                "site_public_base_url",
            ):
                public_views_module.SITE_DEFAULTS.pop(key, None)
            html = public_views_module.maintenance_page(
                {
                    "site": {
                        "maintenance_enabled": "1",
                        "maintenance_text": "Сервисное окно\nmarketing@stammbeer.ru",
                    }
                }
            )
        finally:
            public_views_module.SITE_DEFAULTS.clear()
            public_views_module.SITE_DEFAULTS.update(original_defaults)
        self.assertIn("Сервисное окно", html)
        self.assertIn("mailto:marketing@stammbeer.ru", html)
        self.assertIn("--maintenance-font-size:24px", html)
        self.assertIn("--maintenance-font-weight:500", html)
        self.assertIn('<link rel="canonical" href="https://stammbeer.ru/">', html)

    def test_beer_page_content_is_cms_managed(self) -> None:
        app = self.make_app()
        save_public_content(
            app.conn,
            {
                "beer_partners_title": "Где найти Stamm Brewing",
                "beer_partners_description": "Партнёры\nи бары",
                "home_content_bg_url": "/media/taproom-bg.jpg",
                "beer_partners_is_visible": "1",
                "beer_partners_sort_order": "20",
                "beer_products_sort_order": "10",
                "beer_partner_name_0": "Bottle Shop",
                "beer_partner_logo_url_0": "/media/partner.svg",
                "beer_partner_url_0": "https://partner.test",
                "beer_partner_size_0": "large",
                "beer_partner_sort_order_0": "10",
                "beer_partner_visible_0": "1",
                "beer_products_title": "Наша продукция",
                "beer_new_title": "Новинки",
                "beer_core_title": "Постоянная линейка",
                "beer_seasonal_title": "Сезонные сорта",
                "beer_products_is_visible": "1",
                "beer_new_is_visible": "1",
                "beer_core_is_visible": "1",
                "beer_seasonal_is_visible": "1",
                "menu_offset_beer_px": "232",
                "menu_mobile_offset_beer_px": "118",
                "beer_untappd_logo_url": "/media/untappd-global.svg",
                "beer_popup_backdrop_color": "#123456",
                "beer_popup_backdrop_opacity": "45",
                "beer_popup_card_color": "#654321",
                "beer_popup_card_opacity": "72",
                "beer_section_gap_px": "104",
                "beer_core_can_gap_px": "22",
                "beer_seasonal_can_gap_px": "28",
                "beer_product_name_0": "Stamm IPA",
                "beer_product_style_0": "IPA",
                "beer_product_abv_0": "6.5%",
                "beer_product_image_url_0": "/media/ipa.png",
                "beer_product_untappd_url_0": "https://untappd.com/b/stamm-ipa",
                "beer_product_category_0": "new",
                "beer_product_sort_order_0": "10",
                "beer_product_visible_0": "1",
                "beer_product_name_1": "Stamm Lager",
                "beer_product_style_1": "Lager",
                "beer_product_abv_1": "4.8%",
                "beer_product_image_url_1": "/media/lager.png",
                "beer_product_category_1": "core",
                "beer_product_sort_order_1": "20",
                "beer_product_visible_1": "1",
                "beer_product_name_24": "Stamm Saison",
                "beer_product_style_24": "Saison",
                "beer_product_abv_24": "5.2%",
                "beer_product_image_url_24": "/media/saison.png",
                "beer_product_category_24": "seasonal",
                "beer_product_sort_order_24": "30",
                "beer_product_visible_24": "1",
            },
        )
        content = get_public_site_content(app.conn)
        self.assertEqual(content["beer"]["partners"][0]["name"], "Bottle Shop")
        self.assertEqual(content["beer"]["beer_partners_sort_order"], "20")
        self.assertEqual(content["beer"]["beer_products_sort_order"], "10")
        html = beer_page(content)
        self.assertLess(html.index('data-beer-block="products"'), html.index('data-beer-block="partners"'))
        self.assertIn('"name":"Пиво","item":"https://stammbeer.ru/beer"', html)
        self.assertIn("Где найти Stamm Brewing", html)
        self.assertIn("Партнёры\nи бары", html)
        self.assertIn('target="_blank"', html)
        self.assertIn("--logo-size:154px", html)
        self.assertIn("width:max-content", html)
        self.assertIn("display:flex; flex-wrap:wrap", html)
        self.assertIn("--section-bg:url", html)
        self.assertIn("linear-gradient(180deg, rgba(16,88,89,.78)", html)
        self.assertIn("max-width:1440px", html)
        self.assertIn("gap:104px", html)
        self.assertIn(".beer-shell { gap:clamp(34px,9vw,52px); }", html)
        self.assertIn(".beer-page { padding:128px 16px 48px; background-size:cover, cover", html)
        self.assertIn("background-attachment:scroll, fixed", html)
        self.assertIn("max-height:58px", html)
        self.assertIn("grid-template-columns:repeat(3,minmax(72px,1fr))", html)
        self.assertIn("width:min(1180px,100%)", html)
        self.assertIn("display:flex; flex-wrap:wrap; justify-content:center", html)
        self.assertIn("gap:var(--beer-can-gap,16px)", html)
        self.assertIn("flex:0 0 calc((100% - var(--beer-can-row-gap-total,112px)) / 8); width:auto; max-width:132px; min-width:0;", html)
        self.assertIn('beer-can-grid--core" style="--beer-can-gap:22px;--beer-can-row-gap-total:154px;', html)
        self.assertIn('beer-can-grid--seasonal" style="--beer-can-gap:28px;--beer-can-row-gap-total:196px;', html)
        self.assertIn(".seasonal-grid { width:min(100%,360px); display:flex; flex-wrap:wrap; justify-content:center; gap:8px 6px; }", html)
        self.assertIn(".seasonal-grid .beer-can { flex:0 0 calc((100% - 24px) / 5); width:auto; max-width:54px; min-width:0; }", html)
        self.assertNotIn("product-subsection--new", html)
        self.assertIn("--menu-offset:232px", html)
        self.assertIn("--menu-mobile-offset:118px", html)
        self.assertIn(".partner-card:hover img", html)
        self.assertNotIn("min-height:132px", html)
        self.assertIn("beer-can--featured", html)
        self.assertIn("Постоянная линейка", html)
        self.assertIn("beer-can--seasonal", html)
        self.assertEqual(len(content["beer"]["products"]), 3)
        self.assertIn("beer-modal", html)
        self.assertIn("beer-modal__mockup", html)
        self.assertIn("rgba(18,52,86,0.45)", html)
        self.assertIn("background:rgba(101,67,33,0.72)", html)
        self.assertIn('const untappdLogoUrl = "/media/untappd-global.svg"', html)
        self.assertNotIn("untappdLogoUrl", html.split("data-product=", 1)[1].split(" aria-label", 1)[0])
        self.assertIn("style.textContent = data.style || ''", html)
        self.assertNotIn(">Stamm IPA</span>", html)
        self.assertIn("https://untappd.com/b/stamm-ipa", html)


    def test_admin_catalog_uses_compact_table_styles(self) -> None:
        html = admin_catalog_page(
            "admin@example.test",
            [{
                "id": "product-1",
                "public_name": "Stamm IPA 0.5",
                "container_type": "can",
                "price_minor": 25000,
                "currency": "RUB",
                "available_quantity": 24,
                "availability_status": "in_stock",
                "latest_stock": 30,
                "latest_reserve": 6,
                "sync_state": "synced",
                "is_published": True,
                "last_synced_at": "2026-06-29",
                "beer_style_id": 7,
                "beer_style_name": "IPA",
            }],
            [{"id": 7, "name": "IPA", "sort_order": 2, "is_visible": 1}],
        )
        self.assertIn("admin-catalog-card", html)
        self.assertIn("admin-catalog-table", html)
        self.assertIn("font-size:12px", html)
        self.assertIn("font-size:11px", html)
        self.assertIn("font-weight:600", html)
        self.assertIn("stamm_admin_catalog_scroll", html)
        self.assertIn("admin-catalog-publication-form", html)
        self.assertIn("Стили пива", html)
        self.assertIn("/admin/catalog/styles", html)
        self.assertIn("/admin/catalog/style-assignment", html)
        self.assertIn("IPA · #2", html)
        self.assertIn("value='7' selected", html)

    def test_business_catalog_groups_products_by_admin_beer_styles(self) -> None:
        app = self.make_app()
        ipa_id = self.add_catalog_item(app, "Stamm Exact IPA", "keg", "stamm-exact-ipa")
        lager_id = self.add_catalog_item(app, "Stamm Helles Lager", "keg", "stamm-helles-lager")

        save_beer_style(app.conn, "IPA", 2, True)
        save_beer_style(app.conn, "Lager", 1, True)
        style_map = {style["name"]: style["id"] for style in beer_styles(app.conn)}
        assign_product_beer_style(app.conn, ipa_id, style_map["IPA"])
        assign_product_beer_style(app.conn, lager_id, style_map["Lager"])

        catalog = public_catalog(app.conn)
        self.assertEqual([item["productId"] for item in catalog["items"]], [lager_id, ipa_id])
        self.assertEqual([item["style"]["name"] for item in catalog["items"]], ["Lager", "IPA"])
        self.assertEqual([style["name"] for style in catalog["meta"]["styles"]], ["Lager", "IPA"])
        self.assertEqual(catalog["meta"]["styles"][0]["itemsCount"], 1)

    def test_business_catalog_exactly_follows_admin_publication_flags(self) -> None:
        app = self.make_app()
        product_id = self.add_catalog_item(app, "Stamm Exact IPA", "keg", "stamm-exact-ipa")
        self.assertEqual([item["productId"] for item in public_catalog(app.conn)["items"]], [product_id])

        publish_product(app.conn, product_id, False)
        self.assertEqual(public_catalog(app.conn)["items"], [])
        self.assertEqual(app.conn.execute("SELECT COUNT(*) FROM business_catalog_items WHERE product_id = ?", (product_id,)).fetchone()[0], 0)

        publish_product(app.conn, product_id, True)
        self.assertEqual([item["productId"] for item in public_catalog(app.conn)["items"]], [product_id])

        app.conn.execute("UPDATE product_overrides SET is_published = 0 WHERE product_id = ?", (product_id,))
        app.conn.execute(
            """
            INSERT INTO business_catalog_items (product_id, slug, public_name, price_minor, currency, container_type, availability_status, search_text)
            VALUES (?, 'stale-visible', 'Stale visible row', 10000, 'RUB', 'keg', 'available', 'Stale visible row')
            """,
            (product_id,),
        )
        app.conn.commit()
        self.assertEqual(public_catalog(app.conn)["items"], [])

        app.conn.execute("UPDATE product_overrides SET is_published = 1 WHERE product_id = ?", (product_id,))
        app.conn.execute("DELETE FROM business_catalog_items WHERE product_id = ?", (product_id,))
        app.conn.commit()
        self.assertEqual([item["productId"] for item in public_catalog(app.conn)["items"]], [product_id])


    def test_public_cms_text_preserves_line_breaks_without_raw_html(self) -> None:
        app = self.make_app()
        save_public_content(
            app.conn,
            {
                "home_news_text": "Строка 1\nСтрока 2\n<script>alert(1)</script>",
                "contacts_address": "Адрес 1\nАдрес 2\n<em>не html</em>",
                "contacts_address_is_visible": "0",
                "contacts_address_color": "#C7B166",
                "contacts_description": "Контакты 1\r\nКонтакты 2\n<strong>не html</strong>",
                "contacts_description_is_visible": "0",
                "contacts_description_color": "#F6F1E3",
            },
        )
        content = get_public_site_content(app.conn)
        self.assertEqual(content["home"]["home_news_text"], "Строка 1\nСтрока 2\n<script>alert(1)</script>")
        self.assertEqual(content["contacts"]["contacts_address"], "Адрес 1\nАдрес 2\n<em>не html</em>")
        self.assertEqual(content["contacts"]["contacts_address_is_visible"], "0")
        self.assertEqual(content["contacts"]["contacts_description"], "Контакты 1\r\nКонтакты 2\n<strong>не html</strong>")
        self.assertEqual(content["contacts"]["contacts_description_is_visible"], "0")
        home_html = home_page(content)
        contacts_html = contacts_page(content)
        self.assertIn("white-space:pre-line", home_html)
        self.assertIn("Строка 1\nСтрока 2", home_html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", home_html)
        self.assertNotIn("<script>alert(1)</script>", home_html)
        self.assertIn("white-space:pre-line", contacts_html)
        self.assertNotIn("Адрес 1\nАдрес 2", contacts_html)
        self.assertNotIn("&lt;em&gt;не html&lt;/em&gt;", contacts_html)
        self.assertNotIn("Контакты 1\r\nКонтакты 2", contacts_html)
        self.assertNotIn("&lt;strong&gt;не html&lt;/strong&gt;", contacts_html)


    def test_admin_content_uploads_logo_and_nav_icon_assets(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        session_id = create_session(app.conn, user["id"])
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        boundary = "----stamm-test-boundary"

        def field(name: str, value: str) -> bytes:
            return f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")

        def file_field(name: str, filename: str, payload: bytes) -> bytes:
            return (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                'Content-Type: image/svg+xml\r\n\r\n'
            ).encode("utf-8") + payload + b"\r\n"

        admin_content_request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/admin/content",
            headers={"Cookie": f"stamm_admin_session={session_id}"},
        )
        admin_content_html = urllib.request.urlopen(admin_content_request, timeout=5).read().decode("utf-8")
        self.assertIn('for="cms-tab-contacts"', admin_content_html)
        self.assertIn("Контакты", admin_content_html)
        self.assertIn("contacts-map-picker", admin_content_html)
        self.assertIn('for="cms-tab-beer"', admin_content_html)
        self.assertIn("beer_core_title", admin_content_html)
        self.assertIn("data-add-beer-product", admin_content_html)
        self.assertIn('data-dynamic-list="beer-products-new"', admin_content_html)
        self.assertIn('data-dynamic-list="beer-products-core"', admin_content_html)
        self.assertIn('data-dynamic-list="beer-products-seasonal"', admin_content_html)
        self.assertIn("data-delete-beer-product", admin_content_html)
        self.assertIn("beer-product-fields", admin_content_html)
        self.assertIn("beer-asset-fields", admin_content_html)
        self.assertIn("beer_untappd_logo_file", admin_content_html)
        self.assertIn("beer_popup_backdrop_color", admin_content_html)
        self.assertIn("beer_popup_backdrop_opacity", admin_content_html)
        self.assertIn("beer_popup_card_color", admin_content_html)
        self.assertIn("beer_popup_card_opacity", admin_content_html)
        self.assertIn("beer_section_gap_px", admin_content_html)
        self.assertIn("beer_core_can_gap_px", admin_content_html)
        self.assertIn("beer_seasonal_can_gap_px", admin_content_html)
        self.assertIn("beer_partners_sort_order", admin_content_html)
        self.assertIn("beer_products_sort_order", admin_content_html)
        self.assertIn('for="cms-tab-gallery"', admin_content_html)
        self.assertIn("gallery_title", admin_content_html)
        self.assertIn("gallery_section_0_title", admin_content_html)
        self.assertIn("gallery_section_0_item_image_file_0", admin_content_html)
        self.assertIn("data-add-gallery-section", admin_content_html)
        self.assertIn("data-add-gallery-item", admin_content_html)
        self.assertIn("data-delete-gallery-section", admin_content_html)
        self.assertIn("data-delete-gallery-item", admin_content_html)
        self.assertIn("site_public_base_url", admin_content_html)
        self.assertIn("site_title", admin_content_html)
        self.assertIn("site_description", admin_content_html)
        self.assertIn("site_yandex_metrika_id", admin_content_html)
        self.assertIn("Yandex Metrika ID", admin_content_html)
        self.assertIn("site_favicon_file", admin_content_html)
        self.assertIn("Рекомендуемый размер — 120×120 px", admin_content_html)
        self.assertIn("site_og_image_file", admin_content_html)
        self.assertIn("mobile_menu_icon_file", admin_content_html)
        self.assertIn("age_gate_text_font_size_px", admin_content_html)
        self.assertIn("age_gate_text_font_weight", admin_content_html)
        self.assertIn("maintenance_font_size_px", admin_content_html)
        self.assertIn("maintenance_font_weight", admin_content_html)
        self.assertIn("maintenance_image_file", admin_content_html)
        self.assertIn("business_guest_text", admin_content_html)
        self.assertIn("business_guest_font_size_px", admin_content_html)
        self.assertIn("business_guest_font_weight", admin_content_html)
        self.assertNotIn("beer_product_untappd_logo_file_0", admin_content_html)
        self.assertIn("stamm_admin_content_scroll", admin_content_html)
        self.assertIn("contacts_map_height_px", admin_content_html)
        self.assertIn("contacts_map_width_px", admin_content_html)
        self.assertIn("Высота карты, px", admin_content_html)
        self.assertIn("Ширина карты, px", admin_content_html)
        self.assertIn("contacts_address_is_visible", admin_content_html)
        self.assertIn("contacts_description_is_visible", admin_content_html)
        self.assertIn("contacts_address_color", admin_content_html)
        self.assertIn("contacts_description_color", admin_content_html)
        self.assertIn('min="180" max="420"', admin_content_html)
        self.assertIn('min="280" max="640"', admin_content_html)
        self.assertIn("api-maps.yandex.ru", admin_content_html)
        self.assertNotIn("Широта<input", admin_content_html)
        self.assertNotIn("Долгота<input", admin_content_html)
        self.assertIn("min-height:220px", admin_content_html)
        self.assertIn("cms-tab-panel", admin_content_html)
        self.assertIn('for="cms-tab-typography"', admin_content_html)
        self.assertIn("Типографика", admin_content_html)
        self.assertIn("typography_product_title_font_size_px", admin_content_html)
        self.assertIn("menu_offset_home_px", admin_content_html)
        self.assertIn("menu_mobile_offset_home_px", admin_content_html)
        self.assertIn("Мобильные отступы от верхнего меню", admin_content_html)
        self.assertIn("Отступ контента от меню — Пиво", admin_content_html)
        self.assertIn("section_bg_home_file", admin_content_html)
        self.assertIn("section_bg_beer_file", admin_content_html)
        self.assertIn("section_bg_business_file", admin_content_html)
        self.assertIn("section_bg_history_file", admin_content_html)
        self.assertIn("section_bg_contacts_file", admin_content_html)
        self.assertIn("section_bg_visit_file", admin_content_html)

        parts = [
            field("home_hero_title", "STAMM"),
            field("home_hero_subtitle", "BREWING"),
            field("home_hero_title_size_px", "150"),
            field("home_hero_title_weight", "900"),
            field("home_hero_subtitle_size_px", "100"),
            field("home_hero_subtitle_weight", "800"),
            field("home_hero_line_gap_px", "24"),
            field("home_logo_url", ""),
            file_field("home_logo_file", "logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='600' height='600'></svg>"),
            field("home_content_bg_url", ""),
            file_field("home_content_bg_file", "taproom.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='2400' height='1600'></svg>"),
            field("home_news_title", "Админская новость"),
            field("home_news_text", "Текст новости из админки"),
            field("home_news_image_url", ""),
            file_field("home_news_image_file", "news.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900'></svg>"),
            field("home_news_link_url", "/news/admin"),
            field("home_news_link_label", "Читать"),
            field("site_public_base_url", "https://admin.example"),
            field("site_title", "Admin Stamm"),
            field("site_description", "Admin SEO description"),
            field("site_yandex_metrika_id", "110732851"),
            field("site_favicon_url", ""),
            file_field("site_favicon_file", "favicon.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='64' height='64'></svg>"),
            field("site_og_image_url", ""),
            file_field("site_og_image_file", "og.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='630'></svg>"),
            field("mobile_menu_icon_url", ""),
            file_field("mobile_menu_icon_file", "mobile-menu.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='64' height='64'></svg>"),
            field("business_min_order_amount_minor", "2500000"),
            field("business_guest_text", "Админский текст для партнёров"),
            field("business_guest_font_size_px", "26"),
            field("business_guest_font_weight", "650"),
            field("age_gate_title", "Админ 18+"),
            field("age_gate_text", "Админский текст 18+"),
            field("age_gate_title_font_size_px", "46"), field("age_gate_title_font_weight", "850"),
            field("age_gate_text_font_size_px", "21"), field("age_gate_text_font_weight", "550"),
            field("age_gate_confirm_label", "Да"), field("age_gate_deny_label", "Нет"),
            field("maintenance_enabled", "1"),
            field("maintenance_text", "Админская шторка marketing@stammbeer.ru"),
            field("maintenance_font_size_px", "32"), field("maintenance_font_weight", "750"),
            field("maintenance_image_url", ""),
            file_field("maintenance_image_file", "maintenance.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='800' height='400'></svg>"),
            field("gallery_title", "Админская галерея"),
            field("gallery_description", "Фото из админки"),
            field("gallery_section_0_title", "Пивоварня"),
            field("gallery_section_0_sort_order", "20"),
            field("gallery_section_0_visible", "1"),
            field("gallery_section_0_item_caption_0", "Зал варки"),
            field("gallery_section_0_item_image_url_0", ""),
            file_field("gallery_section_0_item_image_file_0", "gallery.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='900'></svg>"),
            field("gallery_section_0_item_size_0", "large"),
            field("gallery_section_0_item_sort_order_0", "10"),
            field("gallery_section_0_item_visible_0", "1"),
            field("gallery_section_1_title", "Ретроспектива"),
            field("gallery_section_1_sort_order", "10"),
            field("gallery_section_1_visible", "1"),
            field("gallery_section_1_item_caption_0", "Удалить фото"),
            field("gallery_section_1_item_image_url_0", "/media/delete-me.jpg"),
            field("gallery_section_1_item_size_0", "small"),
            field("gallery_section_1_item_sort_order_0", "20"),
            field("gallery_section_1_item_visible_0", "1"),
            field("gallery_section_1_delete", "1"),
            field("contact_email_label_0", "Основной"), field("contact_email_value_0", "admin@stamm.test"), field("contact_email_sort_order_0", "10"), field("contact_email_visible_0", "on"),
            field("contact_email_label_1", "Скрытая почта"), field("contact_email_value_1", "hidden-admin@stamm.test"), field("contact_email_sort_order_1", "20"),
            field("contact_phone_label_0", "Отдел продаж"), field("contact_phone_value_0", "+7 999 000-00-00"), field("contact_phone_sort_order_0", "10"), field("contact_phone_visible_0", "on"),
            field("contacts_address", "Админский адрес завода\nкорпус 1"),
            field("contacts_address_is_visible", "1"), field("contacts_address_color", "#C7B166"),
            field("contacts_description", "Описание контактов из админки"),
            field("contacts_description_is_visible", "1"), field("contacts_description_color", "#F6F1E3"),
            field("contacts_map_lat", "55.7100"), field("contacts_map_lng", "37.6100"),
            field("contacts_map_zoom", "14"), field("contacts_map_height_px", "260"), field("contacts_map_width_px", "380"), field("contacts_map_title", "Админская точка Stamm"),
            field("typography_nav_font_size_px", "19"), field("typography_page_title_font_size_px", "54"),
            field("typography_body_font_size_px", "18"), field("typography_contact_text_font_size_px", "22"),
            field("typography_product_title_font_size_px", "20"), field("typography_price_font_size_px", "24"),
            field("typography_cart_font_size_px", "16"),
            field("menu_offset_home_px", "210"), field("menu_offset_beer_px", "230"),
            field("menu_offset_visit_px", "190"), field("menu_offset_history_px", "200"),
            field("menu_offset_business_px", "240"), field("menu_offset_contacts_px", "220"),
            field("menu_mobile_offset_home_px", "96"), field("menu_mobile_offset_beer_px", "98"),
            field("menu_mobile_offset_visit_px", "92"), field("menu_mobile_offset_history_px", "94"),
            field("menu_mobile_offset_business_px", "100"), field("menu_mobile_offset_contacts_px", "97"),
            field("section_bg_home_url", ""), file_field("section_bg_home_file", "bg-home.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900'></svg>"), field("section_bg_home_enabled", "1"),
            field("section_bg_beer_url", ""), file_field("section_bg_beer_file", "bg-beer.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900'></svg>"), field("section_bg_beer_enabled", "1"),
            field("section_bg_business_url", ""), file_field("section_bg_business_file", "bg-business.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900'></svg>"), field("section_bg_business_enabled", "1"),
            field("section_bg_history_url", ""), file_field("section_bg_history_file", "bg-gallery.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900'></svg>"), field("section_bg_history_enabled", "1"),
            field("section_bg_contacts_url", ""), file_field("section_bg_contacts_file", "bg-contacts.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900'></svg>"), field("section_bg_contacts_enabled", "1"),
            field("section_bg_visit_url", ""), file_field("section_bg_visit_file", "bg-visit.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='900'></svg>"), field("section_bg_visit_enabled", "1"),
            field("beer_untappd_logo_url", ""),
            file_field("beer_untappd_logo_file", "untappd.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='512' height='512'></svg>"),
            field("beer_popup_backdrop_color", "#224466"), field("beer_popup_backdrop_opacity", "35"),
            field("beer_popup_card_color", "#335577"), field("beer_popup_card_opacity", "80"),
            field("beer_partners_sort_order", "30"), field("beer_products_sort_order", "5"),
            field("beer_section_gap_px", "96"),
            field("beer_core_can_gap_px", "18"), field("beer_seasonal_can_gap_px", "26"),
            field("menu_beer_label", "Пиво"), field("menu_beer_sort_order", "10"), field("menu_beer_visible", "on"),
            field("menu_visit_label", "Посетить пивоварню"), field("menu_visit_sort_order", "20"), field("menu_visit_visible", "on"),
            field("menu_history_label", "Галерея"), field("menu_history_sort_order", "30"), field("menu_history_visible", "on"),
            field("menu_business_label", "Бизнес"), field("menu_business_sort_order", "40"), field("menu_business_visible", "on"),
            field("menu_contacts_label", "Контакты"), field("menu_contacts_sort_order", "50"), field("menu_contacts_visible", "on"),
            field("action_tg_label", "TG"), field("action_tg_href", "https://t.me/"), field("action_tg_icon_url", ""), field("action_tg_sort_order", "10"), field("action_tg_visible", "on"),
            file_field("action_tg_icon_file", "tg.svg", b"<svg xmlns='http://www.w3.org/2000/svg' width='512' height='512'></svg>"),
            field("action_vk_label", "VK"), field("action_vk_href", "https://vk.com/"), field("action_vk_icon_url", ""), field("action_vk_sort_order", "20"), field("action_vk_visible", "on"),
            field("action_untappd_label", "Untappd"), field("action_untappd_href", "https://untappd.com/"), field("action_untappd_icon_url", ""), field("action_untappd_sort_order", "30"), field("action_untappd_visible", "on"),
            field("action_cart_label", "Корзина"), field("action_cart_href", "/business#cart"), field("action_cart_icon_url", ""), field("action_cart_sort_order", "40"), field("action_cart_visible", "on"),
            field("action_account_label", "Личный кабинет"), field("action_account_href", "/account"), field("action_account_icon_url", ""), field("action_account_sort_order", "50"), field("action_account_visible", "on"),
        ]
        body = b"".join(parts) + f"--{boundary}--\r\n".encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/admin/content/save",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Cookie": f"stamm_admin_session={session_id}"},
            method="POST",
        )
        try:
            response = urllib.request.build_opener(NoRedirect).open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        self.assertEqual(response.status, 303)
        content = get_public_site_content(app.conn)
        self.assertTrue(content["home"]["home_logo_url"].startswith("/media/home-logo-"))
        self.assertTrue(content["home"]["home_news_image_url"].startswith("/media/home-news-"))
        self.assertTrue(content["home"]["home_content_bg_url"].startswith("/media/home-content-bg-"))
        self.assertTrue(content["site"]["site_favicon_url"].startswith("/media/favicon-"))
        self.assertTrue(content["site"]["site_og_image_url"].startswith("/media/og-image-"))
        self.assertTrue(content["site"]["mobile_menu_icon_url"].startswith("/media/mobile-menu-"))
        self.assertEqual(content["site"]["site_public_base_url"], "https://admin.example")
        self.assertEqual(content["site"]["site_title"], "Admin Stamm")
        self.assertEqual(content["site"]["site_yandex_metrika_id"], "110732851")
        self.assertTrue(content["site"]["maintenance_image_url"].startswith("/media/maintenance-"))
        self.assertEqual(content["site"]["maintenance_font_size_px"], "32")
        self.assertEqual(content["site"]["age_gate_text_font_weight"], "550")
        maintenance_html = maintenance_page(content)
        self.assertIn(content["site"]["maintenance_image_url"], maintenance_html)
        self.assertIn("maintenance-image", maintenance_html)
        self.assertIn("--maintenance-font-size:32px", maintenance_html)
        self.assertIn("--maintenance-font-weight:750", maintenance_html)
        self.assertIn("place-items:start center", maintenance_html)
        self.assertIn("box-shadow:none", maintenance_html)
        self.assertIn("background:transparent; border-radius:0", maintenance_html)
        self.assertEqual(content["business"]["business_guest_text"], "Админский текст для партнёров")
        self.assertEqual(content["business"]["business_guest_font_weight"], "650")
        self.assertEqual(content["home"]["home_news_title"], "Админская новость")
        self.assertEqual(content["home"]["home_news_link_url"], "/news/admin")
        self.assertEqual(content["home"]["home_hero_line_gap_px"], "24")
        self.assertEqual(content["contacts"]["emails"][0]["value"], "admin@stamm.test")
        self.assertTrue(content["contacts"]["emails"][0]["is_visible"])
        self.assertFalse(content["contacts"]["emails"][1]["is_visible"])
        self.assertIn("Админский адрес завода", contacts_page(content))
        self.assertNotIn("hidden-admin@stamm.test", contacts_page(content))
        self.assertIn("Админская точка Stamm", contacts_page(content))
        self.assertIn("--stamm-page-title-font-size:54px", contacts_page(content))
        self.assertIn("--stamm-product-title-font-size:20px", business_storefront_page(content))
        self.assertIn("--stamm-price-font-size:24px", business_storefront_page(content))
        self.assertEqual(content["layout"]["menu_offset_home_px"], "210")
        self.assertEqual(content["layout"]["menu_mobile_offset_home_px"], "96")
        self.assertIn("--menu-offset:210px", home_page(content))
        self.assertIn("--menu-mobile-offset:96px", home_page(content))
        self.assertIn("body.home-body > main", home_page(content))
        self.assertIn("padding-top:var(--menu-mobile-offset,104px) !important", home_page(content))
        self.assertIn("--menu-mobile-offset:97px", contacts_page(content))
        self.assertIn("--menu-mobile-offset:100px", business_storefront_page(content))
        self.assertTrue(content["beer"]["beer_untappd_logo_url"].startswith("/media/beer-untappd-"))
        self.assertEqual(content["beer"]["beer_popup_backdrop_color"], "#224466")
        self.assertEqual(content["beer"]["beer_popup_backdrop_opacity"], "35")
        self.assertEqual(content["beer"]["beer_popup_card_color"], "#335577")
        self.assertEqual(content["beer"]["beer_popup_card_opacity"], "80")
        self.assertEqual(content["beer"]["beer_partners_sort_order"], "30")
        self.assertEqual(content["beer"]["beer_products_sort_order"], "5")
        self.assertEqual(content["beer"]["beer_section_gap_px"], "96")
        self.assertEqual(content["beer"]["beer_core_can_gap_px"], "18")
        self.assertEqual(content["beer"]["beer_seasonal_can_gap_px"], "26")
        self.assertEqual(content["gallery"]["gallery_title"], "Админская галерея")
        self.assertEqual(content["gallery"]["sections"][0]["title"], "Пивоварня")
        self.assertTrue(content["gallery"]["sections"][0]["items"][0]["image_url"].startswith("/media/gallery-0-0-"))
        self.assertEqual(content["gallery"]["sections"][0]["items"][0]["size"], "large")
        self.assertIn("Пивоварня", gallery_page(content))
        self.assertNotIn("Ретроспектива", gallery_page(content))
        self.assertNotIn("/media/delete-me.jpg", gallery_page(content))
        self.assertIn("--menu-offset:210px", home_page(content))
        self.assertIn("--menu-offset:220px", contacts_page(content))
        self.assertIn("--menu-offset:240px", business_storefront_page(content))
        self.assertTrue(content["layout"]["section_bg_beer_url"].startswith("/media/section-bg-beer-"))
        self.assertTrue(content["layout"]["section_bg_history_url"].startswith("/media/section-bg-history-"))
        self.assertTrue(content["layout"]["section_bg_contacts_url"].startswith("/media/section-bg-contacts-"))
        self.assertIn(content["layout"]["section_bg_home_url"], home_page(content))
        self.assertIn(content["layout"]["section_bg_beer_url"], beer_page(content))
        self.assertIn(content["layout"]["section_bg_business_url"], business_storefront_page(content))
        self.assertIn(content["layout"]["section_bg_history_url"], gallery_page(content))
        self.assertIn(content["layout"]["section_bg_contacts_url"], contacts_page(content))
        self.assertIn(content["layout"]["section_bg_visit_url"], public_views_module.public_placeholder_page("Посетить пивоварню", "visit", content))
        tg = next(item for item in content["actions"] if item["key"] == "tg")
        self.assertTrue(tg["icon_url"].startswith("/media/nav-tg-"))
        self.assertIn(content["home"]["home_logo_url"], home_page(content))
        self.assertIn(content["home"]["home_news_image_url"], home_page(content))
        self.assertTrue(content["home"]["home_content_bg_url"].startswith("/media/home-content-bg-"))
        self.assertIn("Админская новость", home_page(content))
        self.assertIn("Читать", home_page(content))
        self.assertIn("--home-line-gap:24px", home_page(content))
        self.assertIn("news-card__image-link", home_page(content))
        self.assertIn(tg["icon_url"], home_page(content))

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
        self.add_catalog_item(app, "Stamm IPA Keg", "keg", "stamm-ipa-keg", "https://cdn.example.test/ipa.jpg")
        self.add_catalog_item(app, "Stamm Pale Ale 0,45 Can", "keg", "stamm-pale-ale-can")
        stale_id = app.conn.execute(
            """
            INSERT INTO products (accounting_name, article, stock_quantity, availability_status, sync_state)
            VALUES ('Reserved old SKU', 'RES-OLD', 0, 'unavailable', 'out_of_stock')
            """
        ).lastrowid
        app.conn.execute(
            """
            INSERT INTO business_catalog_items (product_id, slug, public_name, price_minor, currency, container_type, availability_status, search_text)
            VALUES (?, 'reserved-old', 'Reserved old SKU', 10000, 'RUB', 'can', 'unavailable', 'Reserved old SKU')
            """,
            (stale_id,),
        )
        app.conn.commit()

        all_items = public_catalog(app.conn)
        self.assertEqual(all_items["meta"]["source"], "local_read_model")
        self.assertEqual(all_items["meta"]["totalLocalItems"], 2)
        self.assertEqual(len(all_items["items"]), 2)
        self.assertEqual(all_items["items"][0]["style"]["name"], "Другие сорта")
        self.assertEqual(all_items["meta"]["styles"][0]["name"], "Другие сорта")

        kegs = public_catalog(app.conn, "keg")
        self.assertEqual(len(kegs["items"]), 1)
        self.assertEqual(kegs["items"][0]["containerType"], "keg")
        self.assertEqual(kegs["items"][0]["imageUrl"], "https://cdn.example.test/ipa.jpg")
        self.assertNotEqual(kegs["items"][0]["subtitle"], "Позиция локального B2B-каталога Stamm Brewing")

        cans = public_catalog(app.conn, "can")
        self.assertEqual(len(cans["items"]), 1)
        self.assertEqual(cans["items"][0]["containerType"], "can")
        self.assertEqual(cans["items"][0]["orderRules"]["step"], 12)
        self.assertEqual(cans["items"][0]["orderRules"]["minQuantity"], 12)
        self.assertEqual(cans["items"][0]["orderRules"]["maxQuantity"], 10)
        self.assertEqual(cans["items"][0]["availability"]["quantity"], 10)
        self.assertEqual(kegs["items"][0]["orderRules"]["step"], 1)
        self.assertEqual(kegs["items"][0]["orderRules"]["maxQuantity"], 10)
        self.assertEqual(public_catalog(app.conn, minimum_order_amount_minor=2500000)["meta"]["minimumOrder"]["amountMinor"], 2500000)

    def test_extract_alcohol_percent_handles_moysklad_description_formats(self) -> None:
        self.assertEqual(extract_alcohol_percent("Крепость: 6,5%. Плотность 14."), 6.5)
        self.assertEqual(extract_alcohol_percent("ABV 5.2% / IBU 35"), 5.2)
        self.assertIsNone(extract_alcohol_percent("Описание без градуса и только объём 0,45 л"))

    def test_public_storefront_page_has_local_api_loading_and_empty_states(self) -> None:
        html = business_storefront_page()
        self.assertIn("/api/public/business/catalog", html)
        self.assertIn("Загружаем каталог", html)
        self.assertIn("Каталог скоро появится", html)
        self.assertIn("Ничего не найдено", html)
        self.assertIn("Не удалось загрузить каталог сайта", html)
        self.assertIn("data-filter=\"keg\"", html)
        self.assertIn("data-filter=\"can\"", html)
        self.assertIn("product__image-fallback", html)
        self.assertIn("quantity__button", html)
        self.assertIn("cart__total", html)
        self.assertNotIn("priceDebug", html)
        self.assertIn("AbortController", html)
        self.assertNotIn("rows.join('\\n')", html)
        self.assertNotIn("dataset.uiBranch", html)
        self.assertIn("Оформить заявку", html)
        self.assertIn("Комментарий к заказу", html)
        self.assertIn("orderComment", html)
        self.assertNotIn('placeholder="Комментарий', html)
        self.assertIn("Минимальная сумма заказа", html)
        self.assertIn("cart__minimum is-below", html)
        self.assertNotIn("До оформления осталось", html)
        self.assertNotIn("Цена продажи", html)
        self.assertIn("normalizeCatalogItem", html)
        self.assertIn("[BusinessCatalog] Catalog load failed", html)
        self.assertIn("[BusinessCatalog] Skipped invalid catalog items", html)
        self.assertIn("[BusinessCatalog] Failed to render item card", html)
        self.assertIn("rejectedItems", html)
        self.assertIn("normalizeQuantity", html)
        self.assertIn("maxOrderQuantity", html)
        self.assertIn("data-quantity-input", html)
        self.assertIn("catalog-style-group", html)
        self.assertIn("catalog-style-title", html)
        self.assertIn("style.name || 'Другие сорта'", html)
        self.assertNotIn("Доступно:", html)
        self.assertNotIn("максимум в заказ", html)
        self.assertIn("submitOrder", html)
        self.assertIn("/api/public/business/order", html)
        self.assertIn("Вам есть 18+?", html)
        self.assertIn("stamm_age_confirmed_session", html)
        self.assertIn("--age-gate-title-size:48px", html)
        self.assertIn("--age-gate-title-weight:900", html)
        self.assertIn("--age-gate-text-size:18px", html)
        self.assertIn("--age-gate-text-weight:500", html)
        self.assertIn("Stamm Brewing</a>", html)
        self.assertNotIn('href="/">Главная</a>', html)
        self.assertIn("Untappd", html)
        self.assertIn("Личный кабинет", html)
        self.assertIn("Jost:wght", html)
        self.assertNotIn("<h1>БИЗНЕС</h1>", html)
        self.assertNotIn("Выберите SKU в каталоге через кнопки", html)
        self.assertNotIn("Объём уточняется", html)
        self.assertNotIn("Позиция локального B2B-каталога Stamm Brewing", html)
        self.assertNotIn("Каталог для баров", html)
        self.assertNotIn("api.moysklad.ru", html)

    def test_public_storefront_routes_open_and_trailing_slashes_redirect(self) -> None:
        app = self.make_app()
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        home = urllib.request.urlopen(base + "/", timeout=5)
        self.assertEqual(home.status, 200)
        home_html = home.read().decode("utf-8")
        self.assertIn("Главная", home_html)
        self.assertIn("STAMM", home_html)
        self.assertIn("BREWING", home_html)
        self.assertIn("home-news", home_html)
        self.assertNotIn("news-card__label", home_html)
        self.assertIn("home-hero", home_html)
        self.assertIn("home-news", home_html)
        self.assertIn("position:fixed", home_html)
        self.assertIn("Вам есть 18+?", home_html)
        self.assertIn("Да, мне есть 18", home_html)
        self.assertIn("Нет, мне нет 18", home_html)
        self.assertIn("sessionStorage", home_html)
        self.assertIn("stamm_age_confirmed_session", home_html)
        self.assertNotIn('href="/">Главная</a>', home_html)

        robots_body = urllib.request.urlopen(base + "/robots.txt", timeout=5).read().decode("utf-8")
        self.assertIn("User-agent: *", robots_body)
        self.assertIn("Disallow: /admin", robots_body)
        self.assertIn("Disallow: /api/", robots_body)
        self.assertIn("Sitemap: https://stammbeer.ru/sitemap.xml", robots_body)
        sitemap_body = urllib.request.urlopen(base + "/sitemap.xml", timeout=5).read().decode("utf-8")
        self.assertIn("<loc>https://stammbeer.ru/beer</loc>", sitemap_body)
        self.assertIn("<loc>https://stammbeer.ru/gallery</loc>", sitemap_body)
        self.assertIn("<loc>https://stammbeer.ru/contacts</loc>", sitemap_body)
        self.assertNotIn("/history", sitemap_body)
        self.assertNotIn("/admin", sitemap_body)
        self.assertNotIn("/api/", sitemap_body)

        gallery_response = urllib.request.urlopen(base + "/gallery", timeout=5)
        self.assertEqual(gallery_response.status, 200)
        gallery_body = gallery_response.read().decode("utf-8")
        self.assertIn("Галерея", gallery_body)
        self.assertIn("gallery-grid", gallery_body)
        legacy_history = open_without_redirects(base + "/history")
        self.assertEqual(legacy_history.status, 303)
        self.assertEqual(legacy_history.headers["Location"], "/gallery")

        for path in ("/business", "/business/catalog"):
            response = urllib.request.urlopen(base + path, timeout=5)
            self.assertEqual(response.status, 200)
            body = response.read().decode("utf-8")
            self.assertIn("Чтобы стать нашим партнёром, напишите на marketing@stammbeer.ru", body)
            self.assertIn("business-guest__message", body)
            self.assertNotIn("business-guest__card", body)
            self.assertNotIn("Корзина", body)
            self.assertNotIn('/business#cart', body)
            self.assertNotIn("/api/public/business/catalog", body)

        from app.modules.auth.security import hash_password
        customer_id = app.conn.execute(
            """
            INSERT INTO customer_accounts (email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json)
            VALUES ('route-buyer@example.com', ?, '7701234567', 'counterparty-route', 'https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-route', 'ООО Route Buyer', '{}')
            """,
            (hash_password("secret123"),),
        ).lastrowid
        app.conn.commit()
        session_id = create_customer_session(app.conn, customer_id)
        auth_request = urllib.request.Request(base + "/business", headers={"Cookie": f"stamm_customer_session={session_id}"})
        auth_body = urllib.request.urlopen(auth_request, timeout=5).read().decode("utf-8")
        self.assertIn("Корзина", auth_body)
        self.assertIn('/business#cart', auth_body)
        self.assertIn("/api/public/business/catalog", auth_body)
        self.assertIn('<link rel="icon" type="image/x-icon" href="/favicon.ico">', auth_body)

        redirects = {"/business/": "/business", "/business/catalog/": "/business/catalog"}
        for path, expected_location in redirects.items():
            response = open_without_redirects(base + path)
            self.assertEqual(response.status, 303)
            self.assertEqual(response.headers["Location"], expected_location)

    def test_media_assets_are_served_with_browser_cache_headers(self) -> None:
        app = self.make_app()
        media_dir = Path("var/media")
        media_dir.mkdir(parents=True, exist_ok=True)
        media_path = media_dir / "cache-test.svg"
        media_path.write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")
        self.addCleanup(lambda: media_path.unlink(missing_ok=True))
        save_public_content(app.conn, {"site_favicon_url": "/media/cache-test.svg"})

        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        response = urllib.request.urlopen(base + "/media/cache-test.svg", timeout=5)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertIn("image/svg", response.headers["Content-Type"])
        self.assertTrue(response.headers["ETag"])
        self.assertTrue(response.headers["Last-Modified"])

        favicon_response = urllib.request.urlopen(base + "/favicon.svg", timeout=5)
        self.assertEqual(favicon_response.status, 200)
        self.assertIn("image/svg", favicon_response.headers["Content-Type"])
        self.assertEqual(favicon_response.headers["Cache-Control"], "public, max-age=31536000, immutable")
        favicon_ico_response = urllib.request.urlopen(base + "/favicon.ico", timeout=5)
        self.assertEqual(favicon_ico_response.status, 200)
        self.assertIn("image/svg", favicon_ico_response.headers["Content-Type"])

        request = urllib.request.Request(base + "/media/cache-test.svg", headers={"If-None-Match": response.headers["ETag"]})
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(raised.exception.code, 304)
        self.assertEqual(raised.exception.headers["Cache-Control"], "public, max-age=31536000, immutable")

    def test_maintenance_mode_closes_public_site_but_not_admin(self) -> None:
        app = self.make_app()
        save_public_content(
            app.conn,
            {
                "maintenance_enabled": "1",
                "maintenance_text": "Сайт находится на технических работах, по всем вопросам пишите marketing@stammbeer.ru",
            },
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        for path in ("/", "/contacts", "/beer", "/business", "/visit", "/api/public/business/catalog"):
            response = open_without_redirects(base + path)
            self.assertEqual(response.status, 503)
            body = response.read().decode("utf-8")
            self.assertIn("Сайт находится на технических работах", body)
            self.assertIn("mailto:marketing@stammbeer.ru", body)

        admin_login = urllib.request.urlopen(base + "/admin/login", timeout=5)
        self.assertEqual(admin_login.status, 200)
        self.assertIn("Вход", admin_login.read().decode("utf-8"))
        admin_user = authenticate(app.conn, "admin", "1")
        admin_cookie = cookie_header(create_session(app.conn, admin_user["id"]))
        admin_public_request = urllib.request.Request(base + "/contacts", headers={"Cookie": admin_cookie})
        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(admin_public_request, timeout=5)
            self.fail("Public contacts must remain behind maintenance even with an admin cookie")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.status, 503)
            self.assertIn("Сайт находится на технических работах", exc.read().decode("utf-8"))

    def test_public_catalog_api_endpoint_returns_local_data(self) -> None:
        app = self.make_app()
        self.add_catalog_item(app, "Stamm IPA Keg", "keg", "stamm-ipa-keg")
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        from app.modules.auth.security import hash_password
        customer_id = app.conn.execute(
            """
            INSERT INTO customer_accounts (email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json)
            VALUES ('catalog-buyer@example.com', ?, '7701234567', 'counterparty-catalog', 'https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-catalog', 'ООО Catalog Buyer', '{}')
            """,
            (hash_password("secret123"),),
        ).lastrowid
        app.conn.commit()
        session_id = create_customer_session(app.conn, customer_id)
        url = f"http://127.0.0.1:{server.server_port}/api/public/business/catalog?containerType=keg"
        anonymous = open_without_redirects(url)
        self.assertEqual(anonymous.code, 401)
        self.assertIn("Чтобы стать нашим партнёром", anonymous.read().decode("utf-8"))
        payload = urllib.request.urlopen(urllib.request.Request(url, headers={"Cookie": f"stamm_customer_session={session_id}"}), timeout=5).read().decode("utf-8")
        data = json.loads(payload)
        self.assertEqual(data["meta"]["source"], "local_read_model")
        self.assertEqual(len(data["items"]), 1)
        item = data["items"][0]
        self.assertEqual(item["name"], "Stamm IPA Keg")
        self.assertEqual(item["containerType"], "keg")
        self.assertEqual(item["price"]["label"], "123 ₽")
        self.assertEqual(item["availability"]["quantity"], 10)
        self.assertEqual(item["orderRules"]["maxQuantity"], 10)
        self.assertIn("productId", item)
        self.assertEqual(data["meta"]["minimumOrder"]["amountMinor"], 1500000)

    def test_public_business_order_api_enforces_minimum_and_can_boxes(self) -> None:
        app = self.make_app()
        keg_id = self.add_catalog_item(app, "Stamm IPA Keg", "keg", "stamm-ipa-keg")
        can_id = self.add_catalog_item(app, "Stamm Pale Ale 0,45 Can", "keg", "stamm-pale-ale-can")
        can_href = "https://api.moysklad.ru/api/remap/1.2/entity/product/can-1"
        app.conn.execute("UPDATE business_catalog_items SET price_minor = 500000 WHERE product_id IN (?, ?)", (keg_id, can_id))
        app.conn.execute("UPDATE products SET external_href = ?, stock_quantity = 24 WHERE id = ?", (can_href, can_id))
        from app.modules.auth.security import hash_password
        customer_id = app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json,
                price_type_id, price_type_href, price_type_name, price_type_meta_json, discount_percent, discount_source_json
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, '{}', 0, '{}')
            """,
            (
                "buyer@example.com",
                hash_password("secret123"),
                "7701234567",
                "counterparty-1",
                "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1",
                "ООО Покупатель",
                "pt-b2b",
                "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b2b",
                "B2B",
            ),
        ).lastrowid
        session_id = create_customer_session(app.conn, customer_id)
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "secret-token",
                "store_href": "https://api.moysklad.ru/api/remap/1.2/entity/store/finished",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            None,
        )
        app.conn.execute(
            """
            UPDATE moysklad_sync_settings
            SET store_id = 'finished', store_name = 'Склад готовой продукции',
                available_stores_json = ?
            WHERE id = 1
            """,
            (
                json.dumps(
                    [
                        {
                            "id": "finished",
                            "href": "https://api.moysklad.ru/api/remap/1.2/entity/store/finished",
                            "name": "Склад готовой продукции",
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/store/finished"},
                        }
                    ],
                    ensure_ascii=False,
                ),
            ),
        )
        app.conn.commit()
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        original_urlopen = urllib.request.urlopen
        captured_order_payloads = []

        def fake_urlopen(request, timeout=10):
            url = request.full_url if hasattr(request, "full_url") else str(request)
            method = getattr(request, "get_method", lambda: "GET")()
            if url.startswith(base):
                return original_urlopen(request, timeout=timeout)
            if "/entity/counterparty/counterparty-1" in url:
                return FakeMoyskladResponse(
                    json.dumps(
                        {
                            "id": "counterparty-1",
                            "name": "ООО Покупатель",
                            "inn": "7701234567",
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1"},
                            "priceType": {
                                "id": "pt-b2b",
                                "name": "B2B",
                                "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b2b"},
                            },
                            "discounts": [],
                        }
                    ).encode("utf-8")
                )
            if "/entity/organization" in url:
                return FakeMoyskladResponse(
                    json.dumps(
                        {
                            "rows": [
                                {
                                    "id": "org-1",
                                    "name": "Stamm Brewing",
                                    "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/organization/org-1"},
                                }
                            ]
                        }
                    ).encode("utf-8")
                )
            if "/entity/customerorder" in url and method == "POST":
                body = json.loads(request.data.decode("utf-8"))
                captured_order_payloads.append(body)
                return FakeMoyskladResponse(
                    json.dumps(
                        {
                            "id": "order-1",
                            "name": "00001",
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/customerorder/order-1"},
                        }
                    ).encode("utf-8")
                )
            raise AssertionError(url)

        urllib.request.urlopen = fake_urlopen
        self.addCleanup(lambda: setattr(urllib.request, "urlopen", original_urlopen))

        below = urllib.request.Request(
            base + "/api/public/business/order",
            data=json.dumps({"items": [{"productId": keg_id, "quantity": 1}]}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"stamm_customer_session={session_id}"},
            method="POST",
        )
        below_response = open_without_redirects(below)
        self.assertEqual(below_response.status, 400)
        self.assertIn("Минимальная сумма заказа", below_response.read().decode("utf-8"))

        invalid_can = urllib.request.Request(
            base + "/api/public/business/order",
            data=json.dumps({"items": [{"productId": can_id, "quantity": 5}]}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"stamm_customer_session={session_id}"},
            method="POST",
        )
        invalid_can_response = open_without_redirects(invalid_can)
        self.assertEqual(invalid_can_response.status, 400)
        self.assertIn("коробками по 12", invalid_can_response.read().decode("utf-8"))

        too_many = urllib.request.Request(
            base + "/api/public/business/order",
            data=json.dumps({"items": [{"productId": can_id, "quantity": 36}]}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"stamm_customer_session={session_id}"},
            method="POST",
        )
        too_many_response = open_without_redirects(too_many)
        self.assertEqual(too_many_response.status, 400)
        too_many_payload = too_many_response.read().decode("utf-8")
        self.assertIn("Нельзя заказать больше доступного количества", too_many_payload)
        self.assertNotIn("доступно только 24", too_many_payload)
        self.assertIn("availableQuantity", too_many_payload)

        valid = urllib.request.Request(
            base + "/api/public/business/order",
            data=json.dumps({"comment": "Позвонить перед доставкой", "items": [{"productId": can_id, "quantity": 12}]}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Cookie": f"stamm_customer_session={session_id}"},
            method="POST",
        )
        valid_payload = json.loads(urllib.request.urlopen(valid, timeout=5).read().decode("utf-8"))
        self.assertTrue(valid_payload["ok"])
        self.assertEqual(valid_payload["externalOrderId"], "order-1")
        self.assertEqual(captured_order_payloads[0]["store"]["meta"]["href"], "https://api.moysklad.ru/api/remap/1.2/entity/store/finished")
        self.assertEqual(captured_order_payloads[0]["agent"]["meta"]["href"], "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1")
        self.assertEqual(captured_order_payloads[0]["positions"][0]["price"], 500000)
        self.assertEqual(captured_order_payloads[0]["positions"][0]["reserve"], 12)
        self.assertEqual(captured_order_payloads[0]["positions"][0]["assortment"]["meta"]["href"], can_href)
        self.assertEqual(captured_order_payloads[0]["description"], "Позвонить перед доставкой")
        self.assertNotIn("name", captured_order_payloads[0])
        saved_order = app.conn.execute("SELECT total_minor, status, comment, external_order_id, external_order_href FROM b2b_orders").fetchone()
        self.assertEqual(saved_order["total_minor"], 6000000)
        self.assertEqual(saved_order["status"], "sent_to_moysklad")
        self.assertEqual(saved_order["comment"], "Позвонить перед доставкой")
        self.assertEqual(saved_order["external_order_id"], "order-1")
        self.assertEqual(saved_order["external_order_href"], "https://api.moysklad.ru/api/remap/1.2/entity/customerorder/order-1")
        saved_item = app.conn.execute("SELECT quantity, price_minor, product_snapshot_json FROM b2b_order_items").fetchone()
        self.assertEqual(saved_item["quantity"], 12)
        snapshot = json.loads(saved_item["product_snapshot_json"])
        self.assertEqual(snapshot["containerType"], "can")
        self.assertEqual(snapshot["price"]["amountMinor"], 500000)
        email_log = app.conn.execute("SELECT message_type, recipient_email, status FROM email_send_logs ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(email_log["message_type"], "order_created")
        self.assertEqual(email_log["recipient_email"], "buyer@example.com")
        self.assertEqual(email_log["status"], "skipped")

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



    def test_manual_catalog_sync_imports_updates_and_keeps_items_unpublished(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "secret-token-1234",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            user["id"],
        )
        app.conn.execute(
            """
            UPDATE moysklad_sync_settings
            SET store_id = 'store-1', store_href = 'https://api.moysklad.ru/api/remap/1.2/entity/store/store-1', store_name = 'Основной склад',
                source_product_folder_id = 'folder-1', source_product_folder_href = 'https://api.moysklad.ru/api/remap/1.2/entity/productfolder/folder-1', source_product_folder_name = 'Пиво'
            WHERE id = 1
            """
        )
        app.conn.commit()
        original_urlopen = urllib.request.urlopen
        stock_urls: list[str] = []

        def fake_urlopen(request, timeout=0):
            if "/entity/productfolder" in request.full_url:
                payload = {"rows": [{"id": "folder-1", "name": "Пиво", "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/folder-1"}}]}
                return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))
            if "/entity/assortment" in request.full_url:
                payload = {
                    "rows": [
                        {
                            "id": "sku-1",
                            "name": "Stamm IPA keg",
                            "article": "IPA-30",
                            "code": "IPA30",
                            "externalCode": "ext-1",
                            "updated": "2026-06-01T08:00:00Z",
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/product/sku-1"},
                            "productFolder": {"meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/folder-1"}},
                            "images": {"rows": [{"miniature": {"downloadHref": "https://cdn.example.test/moysklad/ipa-mini.jpg"}}]},
                        },
                        {
                            "id": "sku-zero",
                            "name": "Zero stock can",
                            "article": "ZERO-CAN",
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/product/sku-zero"},
                            "productFolder": {"meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/folder-1"}},
                            "salePrices": [{"value": 5555, "priceType": {"name": "Цена продажи"}}],
                        },
                        {
                            "id": "sku-reserved",
                            "name": "Reserved lager can",
                            "article": "RES-CAN",
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/product/sku-reserved"},
                            "productFolder": {"meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/folder-1"}},
                            "salePrices": [{"value": 7777, "priceType": {"name": "Цена продажи"}}],
                        }
                    ]
                }
                return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))
            if "/entity/product/sku-1" in request.full_url and "/images" not in request.full_url:
                payload = {
                    "id": "sku-1",
                    "name": "Stamm IPA keg",
                    "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/product/sku-1"},
                    "description": "Крепость: 6,5%. Горький IPA.",
                    "salePrices": [
                        {"value": 999, "priceType": {"name": "Закупочная цена"}},
                        {"value": 12345, "priceType": {"name": "Цена продажи"}},
                        {
                            "value": 9800,
                            "priceType": {
                                "id": "pt-b2b",
                                "name": "B2B Stamm",
                                "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b2b"},
                            },
                        },
                    ],
                }
                return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))
            if "/report/stock/bystore" in request.full_url:
                stock_urls.append(request.full_url)
                payload = {
                    "rows": [
                        {
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/product/sku-1?expand=supplier"},
                            "stockByStore": [{
                                "stock": 7,
                                "reserve": 1,
                                "inTransit": 0,
                                "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/store/store-1"},
                            }],
                        },
                        {
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/product/sku-zero"},
                            "stockByStore": [{
                                "quantity": 0,
                                "reserve": 0,
                                "inTransit": 0,
                                "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/store/store-1"},
                            }],
                        },
                        {
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/product/sku-reserved"},
                            "stockByStore": [{
                                "stock": 5,
                                "reserve": 5,
                                "inTransit": 0,
                                "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/store/store-1"},
                            }],
                        }
                    ]
                }
                return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))
            raise AssertionError(request.full_url)

        urllib.request.urlopen = fake_urlopen
        try:
            first = run_manual_catalog_sync(app.conn, user["id"], diagnostic_mode=True)
            synced_product_id = app.conn.execute("SELECT id FROM products WHERE external_id = 'sku-1'").fetchone()["id"]
            publish_product(app.conn, synced_product_id, True)
            second = run_manual_catalog_sync(app.conn, user["id"])
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertTrue(stock_urls)
        self.assertNotIn("filter=", stock_urls[0])
        self.assertIn("stockMode=positiveOnly", stock_urls[0])
        self.assertEqual(first["stats"]["folderMatched"], 3)
        self.assertEqual(first["stats"]["found"], 1)
        self.assertEqual(first["stats"]["skippedNoPositiveAvailability"], 2)
        self.assertEqual(first["stats"]["created"], 1)
        self.assertEqual(first["stats"]["updated"], 0)
        self.assertEqual(first["stats"]["salePricesFetchedByHref"], 1)
        self.assertEqual(second["stats"]["created"], 0)
        self.assertEqual(second["stats"]["updated"], 1)
        products = admin_catalog_items(app.conn)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["accounting_name"], "Stamm IPA keg")
        self.assertEqual(products[0]["container_type"], "keg")
        self.assertEqual(products[0]["price_minor"], 12345)
        self.assertEqual(products[0]["image_url"], "https://cdn.example.test/moysklad/ipa-mini.jpg")
        self.assertEqual(products[0]["stock_quantity"], 6)
        self.assertEqual(products[0]["available_quantity"], 6)
        self.assertEqual(products[0]["latest_stock"], 7)
        self.assertEqual(products[0]["latest_reserve"], 1)
        self.assertTrue(first["stats"]["diagnosticSample"][0]["matched"])
        self.assertEqual(first["stats"]["diagnosticSample"][0]["available"], 6)
        self.assertEqual(first["stats"]["diagnosticSample"][0]["savedAvailabilityStatus"], "available")
        diagnostics = latest_sync_diagnostics(app.conn)
        self.assertIsNotNone(diagnostics)
        self.assertEqual(diagnostics["folderCandidates"][0]["name"], "Stamm IPA keg")
        self.assertEqual(diagnostics["stockReportRows"][0]["available"], 6)
        self.assertTrue(diagnostics["matching"][0]["matched"])
        self.assertEqual(diagnostics["dbWrites"][0]["savedAvailable"], 6)
        self.assertEqual(diagnostics["localCatalogAfterSync"][0]["stock_quantity"], 6)
        self.assertTrue(products[0]["is_published"])
        personalized_catalog = public_catalog(
            app.conn,
            customer_price_type_href="https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b2b",
            customer_price_type_id="pt-b2b",
            customer_price_type_name="B2B Stamm",
        )
        self.assertEqual(personalized_catalog["items"][0]["price"]["amountMinor"], 9800)
        self.assertEqual(personalized_catalog["items"][0]["price"]["pricingSource"], "price_type")
        self.assertNotEqual(personalized_catalog["items"][0]["priceDiagnostics"]["availablePriceTypes"], [])
        unavailable_id = app.conn.execute(
            """
            INSERT INTO products (accounting_name, external_href, stock_quantity, availability_status, sync_state)
            VALUES ('Unavailable stale SKU', 'stale-zero', 0, 'unavailable', 'out_of_stock')
            """
        ).lastrowid
        with self.assertRaises(ValueError):
            publish_product(app.conn, unavailable_id, True)
        self.assertEqual(app.conn.execute("SELECT COUNT(*) FROM business_catalog_items").fetchone()[0], 1)
        self.assertEqual(app.conn.execute("SELECT COUNT(*) FROM moysklad_sync_jobs WHERE status = 'success'").fetchone()[0], 2)
        self.assertEqual(app.conn.execute("SELECT COUNT(*) FROM moysklad_sync_logs").fetchone()[0], 4)

        publish_product(app.conn, products[0]["id"], True)
        self.assertEqual(app.conn.execute("SELECT COUNT(*) FROM business_catalog_items").fetchone()[0], 1)
        public_item = public_catalog(app.conn)["items"][0]
        self.assertEqual(public_item["imageUrl"], "https://cdn.example.test/moysklad/ipa-mini.jpg")
        self.assertEqual(public_item["alcoholLabel"], "6,5%")


    def test_manual_catalog_sync_recursively_includes_child_product_folders(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "secret-token-1234",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            user["id"],
        )
        root_href = "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/root"
        child_href = "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/child"
        grandchild_href = "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/grandchild"
        sku_href = "https://api.moysklad.ru/api/remap/1.2/entity/product/sku-child"
        app.conn.execute(
            """
            UPDATE moysklad_sync_settings
            SET store_id = 'store-1', store_href = 'https://api.moysklad.ru/api/remap/1.2/entity/store/store-1', store_name = 'Основной склад',
                source_product_folder_id = 'root', source_product_folder_href = ?, source_product_folder_name = 'Продукция'
            WHERE id = 1
            """,
            (root_href,),
        )
        app.conn.commit()
        original_urlopen = urllib.request.urlopen

        def fake_urlopen(request, timeout=0):
            if "/entity/productfolder" in request.full_url:
                payload = {
                    "rows": [
                        {"id": "root", "name": "Продукция", "meta": {"href": root_href}},
                        {"id": "child", "name": "Линейка", "meta": {"href": child_href}, "parent": {"meta": {"href": root_href}}},
                        {"id": "grandchild", "name": "IPA", "meta": {"href": grandchild_href}, "parent": {"meta": {"href": child_href}}},
                    ]
                }
                return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))
            if "/entity/assortment" in request.full_url:
                payload = {
                    "rows": [
                        {
                            "id": "sku-child",
                            "name": "Nested IPA 0,45 can",
                            "article": "IPA-CAN",
                            "meta": {"href": sku_href},
                            "productFolder": {"meta": {"href": grandchild_href}},
                            "salePrices": [{"value": 9900, "priceType": {"name": "Цена продажи"}}],
                        }
                    ]
                }
                return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))
            if "/report/stock/bystore" in request.full_url:
                return FakeMoyskladResponse(json.dumps({"rows": [{"meta": {"href": sku_href}, "stockByStore": [{"stock": 2, "reserve": 0, "inTransit": 0, "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/store/store-1"}}]}]}).encode("utf-8"))
            raise AssertionError(request.full_url)

        urllib.request.urlopen = fake_urlopen
        try:
            result = run_manual_catalog_sync(app.conn, user["id"])
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertEqual(result["stats"]["folderScopeCount"], 3)
        self.assertEqual(result["stats"]["assortmentRowsScanned"], 1)
        self.assertEqual(result["stats"]["found"], 1)
        product = admin_catalog_items(app.conn)[0]
        self.assertEqual(product["source_folder_href"], grandchild_href)
        self.assertEqual(product["container_type"], "can")


    def test_moysklad_auto_sync_status_uses_interval_and_compact_history(self) -> None:
        app = self.make_app()
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "token",
                "store_href": "https://api.moysklad.ru/api/remap/1.2/entity/store/store-1",
                "source_product_folder_href": "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/folder-1",
                "include_child_folders": True,
                "full_sync_interval_minutes": "60",
                "stock_sync_interval_minutes": "30",
                "is_enabled": True,
            },
            None,
        )
        app.conn.execute(
            """
            INSERT INTO moysklad_sync_jobs (type, status, trigger_source, started_at, finished_at, error_summary)
            VALUES
              ('auto_catalog', 'success', 'auto', '2999-07-01T10:00:00Z', '2999-07-01T10:01:00Z', NULL),
              ('auto_catalog', 'failed', 'auto', '2026-07-01T09:00:00Z', '2026-07-01T09:01:00Z', 'ошибка авторизации'),
              ('auto_catalog', 'success', 'auto', '2026-07-01T08:00:00Z', '2026-07-01T08:01:00Z', NULL),
              ('auto_catalog', 'success', 'auto', '2026-07-01T07:00:00Z', '2026-07-01T07:01:00Z', NULL)
            """
        )
        app.conn.commit()

        history = compact_auto_sync_history(app.conn)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["status"], "success")
        self.assertEqual(history[1]["error"], "ошибка авторизации")
        status = auto_sync_status(app.conn)
        self.assertTrue(status["enabled"])
        self.assertTrue(status["configured"])
        skipped = run_auto_catalog_sync_if_due(app.conn)
        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(skipped["reason"], "not_due")


    def test_moysklad_auto_sync_recovers_interrupted_running_jobs(self) -> None:
        app = self.make_app()
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "token",
                "store_href": "https://api.moysklad.ru/api/remap/1.2/entity/store/store-1",
                "source_product_folder_href": "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/folder-1",
                "include_child_folders": True,
                "full_sync_interval_minutes": "60",
                "stock_sync_interval_minutes": "30",
                "is_enabled": True,
            },
            None,
        )
        old_running_id = app.conn.execute(
            """
            INSERT INTO moysklad_sync_jobs (type, status, trigger_source, started_at, stats_json)
            VALUES ('auto_catalog', 'running', 'auto', '2000-01-01T00:00:00Z', '{}')
            """
        ).lastrowid
        recent_running_id = app.conn.execute(
            """
            INSERT INTO moysklad_sync_jobs (type, status, trigger_source, started_at, stats_json)
            VALUES ('auto_catalog', 'running', 'auto', ?, '{}')
            """,
            (utc_now_iso(),),
        ).lastrowid
        app.conn.commit()

        self.assertEqual(recover_stale_auto_sync_jobs(app.conn, stale_after_minutes=60), 1)
        old_job = app.conn.execute("SELECT status, finished_at, error_summary FROM moysklad_sync_jobs WHERE id = ?", (old_running_id,)).fetchone()
        recent_job = app.conn.execute("SELECT status FROM moysklad_sync_jobs WHERE id = ?", (recent_running_id,)).fetchone()
        self.assertEqual(old_job["status"], "failed")
        self.assertIsNotNone(old_job["finished_at"])
        self.assertIn("прервана", old_job["error_summary"])
        self.assertEqual(recent_job["status"], "running")
        self.assertEqual(
            app.conn.execute("SELECT error_code FROM moysklad_sync_logs WHERE job_id = ?", (old_running_id,)).fetchone()["error_code"],
            "AUTO_SYNC_INTERRUPTED",
        )

        status = auto_sync_status(app.conn)
        self.assertTrue(status["running"])
        self.assertFalse(status["due"])

    def test_moysklad_reference_refresh_and_selection_persist_api_entities(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "secret-token-1234",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            user["id"],
        )
        original_urlopen = urllib.request.urlopen

        def fake_urlopen(request, timeout=0):
            if "/entity/store" in request.full_url:
                payload = {
                    "rows": [
                        {
                            "id": "store-1",
                            "name": "Основной склад",
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/store/store-1"},
                        }
                    ]
                }
                return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))
            if "/entity/productfolder" in request.full_url:
                payload = {
                    "rows": [
                        {
                            "id": "folder-1",
                            "name": "Пиво",
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/folder-1"},
                        }
                    ]
                }
                return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))
            raise AssertionError(request.full_url)

        urllib.request.urlopen = fake_urlopen
        try:
            counts = refresh_integration_references(app.conn)
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertEqual(counts, {"stores": 1, "folders": 1})
        settings = serialize_settings(get_settings(app.conn))
        self.assertEqual(settings["availableStores"][0]["name"], "Основной склад")
        self.assertEqual(settings["availableProductFolders"][0]["name"], "Пиво")

        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "store_href": "https://api.moysklad.ru/api/remap/1.2/entity/store/store-1",
                "source_product_folder_href": "https://api.moysklad.ru/api/remap/1.2/entity/productfolder/folder-1",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            user["id"],
        )
        selected = serialize_settings(get_settings(app.conn))
        self.assertEqual(selected["selectedStore"]["id"], "store-1")
        self.assertEqual(selected["selectedStore"]["name"], "Основной склад")
        self.assertEqual(selected["sourceProductFolder"]["id"], "folder-1")
        self.assertEqual(selected["sourceProductFolder"]["name"], "Пиво")
        self.assertTrue(selected["includeChildFolders"])

    def test_moysklad_test_connection_uses_get_without_content_type_body(self) -> None:
        captured = {}
        original_urlopen = urllib.request.urlopen

        def fake_urlopen(request, timeout=0):
            captured["request"] = request
            captured["timeout"] = timeout
            payload = gzip.compress(json.dumps({"rows": [{"name": "Stamm Test"}]}).encode("utf-8"))
            return FakeMoyskladResponse(payload, content_encoding="gzip")

        urllib.request.urlopen = fake_urlopen
        try:
            client = MoyskladClient("token-123", timeout=7)
            result = client.test_connection()
        finally:
            urllib.request.urlopen = original_urlopen

        request = captured["request"]
        self.assertTrue(result.ok)
        self.assertEqual(result.account_name, "Stamm Test")
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(request.get_method(), "GET")
        self.assertIn("/entity/organization?limit=1", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer token-123")
        self.assertEqual(request.get_header("Accept"), "application/json;charset=utf-8")
        self.assertEqual(request.get_header("Accept-encoding"), "gzip")
        self.assertFalse(request.has_header("Content-type"))
        self.assertIsNone(getattr(request, "data", None))

    def test_moysklad_source_folder_href_guard(self) -> None:
        client = MoyskladClient("token", api_base_url="https://api.moysklad.ru/api/remap/1.2")
        with self.assertRaises(ValueError):
            client.fetch_source_folder("https://example.test/entity/productfolder/1")

    def test_customer_registration_checks_moysklad_counterparty_by_inn(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "token-123",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            user["id"],
        )
        captured = {}
        original_urlopen = urllib.request.urlopen

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["auth"] = request.get_header("Authorization")
            payload = {
                "rows": [
                    {
                        "id": "counterparty-1",
                        "name": "ООО Штамм Партнёр",
                        "inn": "7701234567",
                        "meta": {
                            "href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1",
                            "type": "counterparty",
                            "mediaType": "application/json",
                        },
                        "discounts": [{"personalDiscount": 12.5}],
                    }
                ]
            }
            return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))

        urllib.request.urlopen = fake_urlopen
        try:
            result = register_customer(app.conn, "7701234567", "partner@example.com", "secret123", "secret123")
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertTrue(result.ok)
        self.assertIsNotNone(result.account)
        self.assertIn("/entity/counterparty", captured["url"])
        self.assertIn("filter=inn%3D7701234567", captured["url"])
        self.assertEqual(captured["auth"], "Bearer token-123")
        account = app.conn.execute("SELECT * FROM customer_accounts WHERE email = 'partner@example.com'").fetchone()
        self.assertIsNotNone(account)
        self.assertEqual(account["inn"], "7701234567")
        self.assertEqual(account["counterparty_id"], "counterparty-1")
        self.assertEqual(account["counterparty_name"], "ООО Штамм Партнёр")
        self.assertIn("counterparty-1", account["counterparty_href"])
        self.assertEqual(account["discount_percent"], 12.5)

    def test_customer_registration_rejects_missing_counterparty_duplicate_email_and_password_mismatch(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "token-123",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            user["id"],
        )
        original_urlopen = urllib.request.urlopen

        def missing_urlopen(request, timeout=0):
            return FakeMoyskladResponse(json.dumps({"rows": []}).encode("utf-8"))

        urllib.request.urlopen = missing_urlopen
        try:
            missing = register_customer(app.conn, "7701234567", "missing@example.com", "secret123", "secret123")
        finally:
            urllib.request.urlopen = original_urlopen
        self.assertFalse(missing.ok)
        self.assertIn("не найден", missing.message)

        mismatch = register_customer(app.conn, "7701234567", "bad@example.com", "secret123", "another123")
        self.assertFalse(mismatch.ok)
        self.assertIn("не совпадают", mismatch.message)

        def found_urlopen(request, timeout=0):
            payload = {"rows": [{"id": "counterparty-1", "name": "ООО Партнёр", "inn": "7701234567", "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1"}}]}
            return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))

        urllib.request.urlopen = found_urlopen
        try:
            created = register_customer(app.conn, "7701234567", "dupe@example.com", "secret123", "secret123")
            duplicate = register_customer(app.conn, "7701234567", "dupe@example.com", "secret123", "secret123")
        finally:
            urllib.request.urlopen = original_urlopen
        self.assertTrue(created.ok)
        self.assertFalse(duplicate.ok)
        self.assertIn("уже зарегистрирован", duplicate.message)

    def test_public_account_login_dashboard_logout_flow_is_separate_from_admin_auth(self) -> None:
        app = self.make_app()
        app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json
            ) VALUES (
                'partner@example.com',
                'pbkdf2_sha256$210000$impossible$hash',
                '7701234567',
                'counterparty-1',
                'https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1',
                'ООО Штамм Партнёр',
                '{}'
            )
            """
        )
        app.conn.commit()
        # Replace the placeholder hash by using the public registration-safe authenticator path.
        from app.modules.auth.security import hash_password

        app.conn.execute("UPDATE customer_accounts SET password_hash = ? WHERE email = ?", (hash_password("secret123"), "partner@example.com"))
        app.conn.commit()

        customer = authenticate_customer(app.conn, "partner@example.com", "secret123", refresh_discount=False)
        self.assertIsNotNone(customer)
        session_id = create_customer_session(app.conn, customer["id"])
        cookie = f"stamm_customer_session={session_id}"
        self.assertEqual(customer_session_from_cookie(cookie), session_id)
        loaded = current_customer(app.conn, cookie)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["counterparty_name"], "ООО Штамм Партнёр")
        self.assertIsNone(current_user(app.conn, cookie))
        order_id = app.conn.execute(
            """
            INSERT INTO b2b_orders (
                number, status, contact_name, company_name, inn, email, phone, city,
                total_minor, currency, source_json, customer_account_id, counterparty_href
            ) VALUES (
                'B2B-LK-1', 'sent_to_moysklad', 'partner@example.com', 'ООО Штамм Партнёр',
                '7701234567', 'partner@example.com', '—', '—', 1250000, 'RUB', '{}', ?, ?
            )
            """,
            (customer["id"], customer["counterparty_href"]),
        ).lastrowid
        app.conn.execute(
            """
            INSERT INTO b2b_order_items (
                order_id, product_id, variant_id, quantity, price_minor, line_total_minor,
                product_snapshot_json, availability_snapshot_json
            ) VALUES (?, NULL, NULL, 24, 50000, 1200000, ?, '{}')
            """,
            (order_id, json.dumps({"name": "Stamm IPA банка"}, ensure_ascii=False)),
        )
        app.conn.commit()

        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        request = urllib.request.Request(base + "/account", headers={"Cookie": cookie})
        page_html = urllib.request.urlopen(request, timeout=5).read().decode("utf-8")
        self.assertIn("ООО Штамм Партнёр", page_html)
        self.assertIn("История заказов", page_html)
        self.assertIn("Заказ 1", page_html)
        self.assertIn("max-height:420px; overflow-y:auto", page_html)
        self.assertIn("overscroll-behavior:contain", page_html)
        self.assertNotIn("B2B-LK-1", page_html)
        self.assertIn("Stamm IPA банка", page_html)
        self.assertIn("Смена пароля", page_html)
        self.assertIn("Забыл пароль", page_html)
        self.assertIn("Выйти", page_html)
        self.assertIn("account-actions account-actions--single-row", page_html)
        self.assertIn('form="logoutForm"', page_html)
        self.assertNotIn("Здесь собраны данные B2B-аккаунта, история заказов и управление паролем.", page_html)
        self.assertIn('form="forgotPasswordForm"', page_html)
        self.assertIn('action="/account/password-reset"', page_html)
        self.assertNotIn("Контрагент МойСклад найден", page_html)
        self.assertNotIn("Диагностика скидки МойСклад", page_html)
        self.assertNotIn("Персональный тип цен", page_html)
        self.assertNotIn("Персональная скидка", page_html)
        self.assertNotIn("Обновлена", page_html)
        self.assertNotIn("Статус связи", page_html)
        self.assertNotIn("Статус: sent_to_moysklad", page_html)
        self.assertNotIn("2026-06-29T", page_html)
        app.conn.execute("UPDATE customer_accounts SET discount_percent = 7.5, discount_synced_at = '2026-06-29T00:00:00Z' WHERE id = ?", (customer["id"],))
        app.conn.commit()
        discounted_html = urllib.request.urlopen(request, timeout=5).read().decode("utf-8")
        self.assertIn("Персональная скидка", discounted_html)
        self.assertIn("7.5%", discounted_html)
        bad_password = open_without_redirects(
            urllib.request.Request(
                base + "/account/password",
                data=urllib.parse.urlencode({"current_password": "wrong", "new_password": "newsecret123", "new_password_confirm": "newsecret123"}).encode("utf-8"),
                headers={"Cookie": cookie},
                method="POST",
            )
        )
        self.assertEqual(bad_password.code, 303)
        self.assertIn("password_error", bad_password.headers["Location"])
        ok_password = open_without_redirects(
            urllib.request.Request(
                base + "/account/password",
                data=urllib.parse.urlencode({"current_password": "secret123", "new_password": "newsecret123", "new_password_confirm": "newsecret123"}).encode("utf-8"),
                headers={"Cookie": cookie},
                method="POST",
            )
        )
        self.assertEqual(ok_password.code, 303)
        self.assertIn("password_result", ok_password.headers["Location"])
        self.assertIsNotNone(authenticate_customer(app.conn, "partner@example.com", "newsecret123", refresh_discount=False))

        anonymous = open_without_redirects(base + "/account")
        self.assertEqual(anonymous.code, 303)
        self.assertEqual(anonymous.headers["Location"], "/account/login")

        save_public_content(
            app.conn,
            {
                "maintenance_enabled": "1",
                "maintenance_text": "Сайт находится на технических работах, по всем вопросам пишите marketing@stammbeer.ru",
            },
        )
        logout_response = open_without_redirects(
            urllib.request.Request(
                base + "/account/logout",
                data=b"",
                headers={"Cookie": cookie},
                method="POST",
            )
        )
        self.assertEqual(logout_response.code, 303)
        self.assertEqual(logout_response.headers["Location"], "/account/login")
        self.assertIn("stamm_customer_session=;", logout_response.headers["Set-Cookie"])
        maintenance_login = open_without_redirects(base + "/account/login")
        self.assertEqual(maintenance_login.status, 503)
        maintenance_body = maintenance_login.read().decode("utf-8")
        self.assertIn("Сайт находится на технических работах", maintenance_body)
        self.assertIn("mailto:marketing@stammbeer.ru", maintenance_body)

    def test_public_catalog_applies_customer_discount_without_changing_base_catalog_price(self) -> None:
        app = self.make_app()
        self.add_catalog_item(app, "Stamm Pils 20л (S)", "keg", "stamm-pils")

        anonymous = public_catalog(app.conn)
        self.assertEqual(anonymous["meta"]["pricingMode"], "base")
        self.assertEqual(anonymous["items"][0]["price"]["amountMinor"], 12300)
        self.assertFalse(anonymous["items"][0]["price"]["isPersonalized"])

        discounted = public_catalog(app.conn, customer_discount_percent=10)
        self.assertEqual(discounted["meta"]["pricingMode"], "personal")
        self.assertEqual(discounted["meta"]["customerDiscountPercent"], 10)
        self.assertEqual(discounted["items"][0]["price"]["baseAmountMinor"], 12300)
        self.assertEqual(discounted["items"][0]["price"]["amountMinor"], 11070)
        self.assertTrue(discounted["items"][0]["price"]["isPersonalized"])
        self.assertTrue(discounted["items"][0]["price"]["showBasePrice"])

        same_price = public_catalog(app.conn, customer_discount_percent=0)
        self.assertFalse(same_price["items"][0]["price"]["showBasePrice"])

    def test_public_catalog_applies_customer_price_type_price_when_available(self) -> None:
        app = self.make_app()
        self.add_catalog_item(app, "Stamm Pils 20л (S)", "keg", "stamm-pils")
        price_type_prices = json.dumps(
            [
                {
                    "value": 9800,
                    "currency": "RUB",
                    "priceTypeId": "pt-b2b",
                    "priceTypeHref": "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b2b",
                    "priceTypeName": "B2B Stamm",
                    "priceTypeMeta": {"href": "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b2b"},
                }
            ],
            ensure_ascii=False,
        )
        app.conn.execute("UPDATE business_catalog_items SET price_type_prices_json = ? WHERE slug = ?", (price_type_prices, "stamm-pils"))
        app.conn.commit()

        catalog = public_catalog(
            app.conn,
            customer_price_type_href="https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b2b",
            customer_price_type_id="pt-b2b",
            customer_price_type_name="B2B Stamm",
        )

        self.assertEqual(catalog["meta"]["pricingMode"], "personal")
        self.assertEqual(catalog["meta"]["customerPriceType"]["name"], "B2B Stamm")
        self.assertEqual(catalog["items"][0]["price"]["amountMinor"], 9800)
        self.assertEqual(catalog["items"][0]["price"]["pricingSource"], "price_type")
        self.assertEqual(catalog["items"][0]["price"]["priceTypeName"], "B2B Stamm")
        self.assertEqual(catalog["items"][0]["priceDiagnostics"]["basePriceMinor"], 12300)
        self.assertEqual(catalog["items"][0]["priceDiagnostics"]["matchedPriceType"]["priceTypeName"], "B2B Stamm")
        self.assertEqual(catalog["meta"]["priceDebugSample"][0]["returnedAmountMinor"], 9800)
        self.assertTrue(catalog["items"][0]["price"]["isPersonalized"])

        app.conn.execute("UPDATE business_catalog_items SET price_type_prices_json = '{}' WHERE slug = ?", ("stamm-pils",))
        app.conn.execute("UPDATE products SET price_type_prices_json = ? WHERE id = (SELECT product_id FROM business_catalog_items WHERE slug = ?)", (price_type_prices, "stamm-pils"))
        app.conn.commit()
        fallback_catalog = public_catalog(
            app.conn,
            customer_price_type_href="https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b2b",
            customer_price_type_id="pt-b2b",
            customer_price_type_name="B2B Stamm",
        )
        self.assertEqual(fallback_catalog["items"][0]["price"]["amountMinor"], 9800)
        self.assertEqual(fallback_catalog["items"][0]["priceDiagnostics"]["matchedPriceType"]["priceTypeName"], "B2B Stamm")

    def test_public_catalog_api_uses_price_type_per_customer_session(self) -> None:
        app = self.make_app()
        self.add_catalog_item(app, "Stamm Pils 20л (S)", "keg", "stamm-pils")
        price_type_prices = json.dumps(
            [
                {"value": 9800, "priceTypeId": "pt-a", "priceTypeHref": "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-a", "priceTypeName": "B2B A"},
                {"value": 8700, "priceTypeId": "pt-b", "priceTypeHref": "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b", "priceTypeName": "B2B B"},
            ],
            ensure_ascii=False,
        )
        app.conn.execute("UPDATE business_catalog_items SET price_type_prices_json = ? WHERE slug = ?", (price_type_prices, "stamm-pils"))
        from app.modules.auth.security import hash_password

        app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json,
                price_type_id, price_type_href, price_type_name, price_type_meta_json, discount_percent, discount_source_json
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, '{}', 0, '{}')
            """,
            (
                "a@example.com",
                hash_password("secret123"),
                "7701234567",
                "counterparty-a",
                "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-a",
                "ООО A",
                "pt-a",
                "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-a",
                "B2B A",
            ),
        )
        account_a = app.conn.execute("SELECT * FROM customer_accounts WHERE email = 'a@example.com'").fetchone()
        app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json,
                price_type_id, price_type_href, price_type_name, price_type_meta_json, discount_percent, discount_source_json
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, '{}', 0, '{}')
            """,
            (
                "b@example.com",
                hash_password("secret123"),
                "7707654321",
                "counterparty-b",
                "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-b",
                "ООО B",
                "pt-b",
                "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b",
                "B2B B",
            ),
        )
        app.conn.commit()
        account_b = app.conn.execute("SELECT * FROM customer_accounts WHERE email = 'b@example.com'").fetchone()
        session_a = create_customer_session(app.conn, account_a["id"])
        session_b = create_customer_session(app.conn, account_b["id"])

        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        guest_response = open_without_redirects(base + "/api/public/business/catalog")
        self.assertEqual(guest_response.code, 401)
        request_a = urllib.request.Request(base + "/api/public/business/catalog", headers={"Cookie": f"stamm_customer_session={session_a}"})
        request_b = urllib.request.Request(base + "/api/public/business/catalog", headers={"Cookie": f"stamm_customer_session={session_b}"})
        response_a = json.loads(urllib.request.urlopen(request_a, timeout=5).read().decode("utf-8"))
        response_b = json.loads(urllib.request.urlopen(request_b, timeout=5).read().decode("utf-8"))

        self.assertEqual(response_a["items"][0]["price"]["amountMinor"], 9800)
        self.assertEqual(response_b["items"][0]["price"]["amountMinor"], 8700)
        self.assertEqual(response_a["meta"]["customerPriceType"]["name"], "B2B A")
        self.assertEqual(response_b["meta"]["customerPriceType"]["name"], "B2B B")

    def test_customer_login_refreshes_moysklad_discount_cache(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "token-123",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            user["id"],
        )
        from app.modules.auth.security import hash_password

        app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json,
                discount_percent, discount_source_json
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', 0, '{}')
            """,
            (
                "discount@example.com",
                hash_password("secret123"),
                "7701234567",
                "counterparty-1",
                "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1",
                "ООО Старая скидка",
            ),
        )
        app.conn.commit()
        original_urlopen = urllib.request.urlopen
        captured_urls = []

        def fake_urlopen(request, timeout=0):
            captured_urls.append(request.full_url)
            payload = {
                "id": "counterparty-1",
                "name": "ООО Новая скидка",
                "inn": "7701234567",
                "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1"},
                "discounts": [{"discount": {"personalDiscount": 15}}],
            }
            return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))

        urllib.request.urlopen = fake_urlopen
        try:
            customer = authenticate_customer(app.conn, "discount@example.com", "secret123")
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertIsNotNone(customer)
        self.assertEqual(customer["discount_percent"], 15)
        self.assertEqual(customer["counterparty_name"], "ООО Новая скидка")
        self.assertIsNotNone(customer["discount_synced_at"])
        self.assertTrue(any("/entity/counterparty/counterparty-1" in url for url in captured_urls))
        self.assertTrue(any("expand=discounts.discount" in url for url in captured_urls))

    def test_customer_login_diagnostics_follow_local_link_and_inn_fallback_when_href_has_empty_discounts(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "token-123",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            user["id"],
        )
        from app.modules.auth.security import hash_password

        app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json,
                discount_percent, discount_source_json
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', 0, '{}')
            """,
            (
                "diagnostic@example.com",
                hash_password("secret123"),
                "7701234567",
                "counterparty-1",
                "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1",
                "ООО Старая связь",
            ),
        )
        app.conn.commit()
        original_urlopen = urllib.request.urlopen
        captured_urls = []

        def fake_urlopen(request, timeout=0):
            captured_urls.append(request.full_url)
            if "/entity/counterparty/counterparty-1" in request.full_url:
                payload = {
                    "id": "counterparty-1",
                    "name": "ООО По href без скидки",
                    "inn": "7701234567",
                    "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1"},
                    "priceType": {
                        "id": "pt-b2b",
                        "name": "B2B Stamm",
                        "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b2b"},
                    },
                    "discounts": [],
                }
            else:
                payload = {
                    "rows": [
                        {
                            "id": "counterparty-1",
                            "name": "ООО По ИНН со скидкой",
                            "inn": "7701234567",
                            "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1"},
                            "priceType": {
                                "id": "pt-b2b",
                                "name": "B2B Stamm",
                                "meta": {"href": "https://api.moysklad.ru/api/remap/1.2/context/companysettings/pricetype/pt-b2b"},
                            },
                            "discounts": [{"discount": {"discount": 10}}],
                        }
                    ]
                }
            return FakeMoyskladResponse(json.dumps(payload).encode("utf-8"))

        urllib.request.urlopen = fake_urlopen
        try:
            customer = authenticate_customer(app.conn, "diagnostic@example.com", "secret123")
        finally:
            urllib.request.urlopen = original_urlopen

        self.assertIsNotNone(customer)
        self.assertEqual(customer["discount_percent"], 10)
        source = json.loads(customer["discount_source_json"])
        self.assertEqual(source["localAccount"]["linkedCounterpartyId"], "counterparty-1")
        self.assertEqual(source["localAccount"]["linkedInn"], "7701234567")
        self.assertEqual(source["refresh"]["selectedAttempt"], "inn")
        self.assertEqual(len(source["refresh"]["attempts"]), 2)
        self.assertEqual(source["moyskladDiscountDiagnostics"]["selectedValue"], 10)
        self.assertEqual(source["counterpartyPriceType"]["priceTypeName"], "B2B Stamm")
        self.assertEqual(customer["price_type_name"], "B2B Stamm")
        self.assertTrue(any("/entity/counterparty/counterparty-1" in url for url in captured_urls))
        self.assertTrue(any("filter=inn%3D7701234567" in url for url in captured_urls))

    def test_customer_login_does_not_return_stale_discount_when_refresh_fails(self) -> None:
        app = self.make_app()
        user = authenticate(app.conn, "admin", "1")
        save_settings(
            app.conn,
            {
                "api_base_url": "https://api.moysklad.ru/api/remap/1.2",
                "token": "token-123",
                "include_child_folders": True,
                "full_sync_interval_minutes": "360",
                "stock_sync_interval_minutes": "120",
                "is_enabled": True,
            },
            user["id"],
        )
        from app.modules.auth.security import hash_password

        app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json,
                discount_percent, discount_source_json
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', 7, '{}')
            """,
            (
                "stale@example.com",
                hash_password("secret123"),
                "7701234567",
                "counterparty-1",
                "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1",
                "ООО Старая скидка",
            ),
        )
        app.conn.commit()
        original_urlopen = urllib.request.urlopen

        def failing_urlopen(request, timeout=0):
            raise urllib.error.URLError("moysklad unavailable")

        urllib.request.urlopen = failing_urlopen
        try:
            with self.assertRaises(DiscountRefreshError):
                authenticate_customer(app.conn, "stale@example.com", "secret123")
        finally:
            urllib.request.urlopen = original_urlopen

        account = app.conn.execute("SELECT discount_percent FROM customer_accounts WHERE email = 'stale@example.com'").fetchone()
        self.assertEqual(account["discount_percent"], 7)

    def test_email_payloads_render_moscow_time(self) -> None:
        app = self.make_app()
        from app.modules.auth.security import hash_password

        app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json,
                discount_percent, discount_source_json
            ) VALUES ('time@example.com', ?, '7701234567', 'counterparty-1',
                'https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1', 'ООО Время', '{}', 0, '{}')
            """,
            (hash_password("secret123"),),
        )
        app.conn.commit()
        customer = app.conn.execute("SELECT * FROM customer_accounts WHERE email = 'time@example.com'").fetchone()
        captured = []
        original_send_email = email_service.send_email
        email_service.send_email = lambda conn, settings, payload: captured.append(payload) or True
        try:
            email_service.send_order_created(
                app.conn,
                app.settings,
                customer,
                "B2B-TIME",
                "2026-07-04T10:00:00Z",
                [{"item": {"name": "Stamm Time", "price": {"amountMinor": 100000}}, "quantity": 1, "lineTotalMinor": 100000}],
                100000,
                "",
            )
            email_service.send_password_reset(app.conn, app.settings, "time@example.com")
        finally:
            email_service.send_email = original_send_email
        self.assertIn("04.07.2026 13:00 МСК", captured[0].text_body)
        self.assertIn("04.07.2026 13:00 МСК", captured[0].html_body)
        self.assertIn("МСК", captured[1].text_body)
        self.assertIn("МСК", captured[1].html_body)


    def test_email_confirmation_and_password_reset_tokens_are_hashed_and_one_time(self) -> None:
        app = self.make_app()
        from app.modules.auth.security import hash_password

        app.conn.execute(
            """
            INSERT INTO customer_accounts (
                email, password_hash, inn, counterparty_id, counterparty_href, counterparty_name, counterparty_meta_json,
                discount_percent, discount_source_json
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', 0, '{}')
            """,
            (
                "mail@example.com",
                hash_password("secret123"),
                "7701234567",
                "counterparty-1",
                "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/counterparty-1",
                "ООО Почта",
            ),
        )
        app.conn.commit()
        account = app.conn.execute("SELECT * FROM customer_accounts WHERE email = 'mail@example.com'").fetchone()

        original_token = email_service.secrets.token_urlsafe
        email_service.secrets.token_urlsafe = lambda size: "verify-token"
        try:
            email_service.send_email_confirmation(app.conn, app.settings, account)
        finally:
            email_service.secrets.token_urlsafe = original_token

        verification = app.conn.execute("SELECT token_hash, used_at FROM customer_email_verification_tokens").fetchone()
        self.assertNotEqual(verification["token_hash"], "verify-token")
        self.assertIsNone(verification["used_at"])
        self.assertTrue(email_service.verify_customer_email(app.conn, "verify-token"))
        self.assertFalse(email_service.verify_customer_email(app.conn, "verify-token"))
        account = app.conn.execute("SELECT email_verified_at FROM customer_accounts WHERE email = 'mail@example.com'").fetchone()
        self.assertIsNotNone(account["email_verified_at"])

        email_service.secrets.token_urlsafe = lambda size: "reset-token"
        try:
            email_service.send_password_reset(app.conn, app.settings, "mail@example.com")
        finally:
            email_service.secrets.token_urlsafe = original_token
        reset = app.conn.execute("SELECT token_hash, used_at FROM customer_password_reset_tokens").fetchone()
        self.assertNotEqual(reset["token_hash"], "reset-token")
        ok, message = email_service.reset_customer_password(app.conn, "reset-token", "newsecret123", "newsecret123")
        self.assertTrue(ok, message)
        self.assertIsNotNone(authenticate_customer(app.conn, "mail@example.com", "newsecret123", refresh_discount=False))
        self.assertFalse(email_service.reset_customer_password(app.conn, "reset-token", "another123", "another123")[0])
        logs = [row["message_type"] for row in app.conn.execute("SELECT message_type FROM email_send_logs ORDER BY id")]
        self.assertEqual(logs, ["email_confirmation", "password_reset"])


if __name__ == "__main__":
    unittest.main()
