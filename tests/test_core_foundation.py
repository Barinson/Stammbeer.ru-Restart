from __future__ import annotations

import gzip
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app.config import Settings, load_settings
from app.integrations.moysklad.catalog_sync import extract_alcohol_percent, infer_container_type, latest_sync_diagnostics, run_manual_catalog_sync
from app.integrations.moysklad.client import MoyskladClient, normalize_counterparty
from app.modules.account.service import (
    DiscountRefreshError,
    authenticate_customer,
    create_customer_session,
    current_customer,
    customer_session_from_cookie,
    register_customer,
)
from app.integrations.moysklad.settings_service import get_settings, refresh_integration_references, save_settings, serialize_settings
from app.modules.email import service as email_service
from app.main import StammApp, admin_stats
from app.modules.catalog.service import admin_catalog_items, public_catalog, publish_product
from app.modules.content.service import get_public_site_content, save_public_content
from app.modules.public_views import beer_page, business_storefront_page, contacts_page, home_page
from app.modules.auth.service import authenticate, change_password, cookie_header, create_session, current_user


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
        self.assertIn("b2b_orders", tables)
        self.assertIn("customer_email_verification_tokens", tables)
        self.assertIn("customer_password_reset_tokens", tables)
        self.assertIn("email_send_logs", tables)
        self.assertIn("email_settings", tables)
        self.assertIn("email_templates", tables)
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
        self.assertIn("Сброс пароля", users_html)

        disable = urllib.request.Request(
            base + "/admin/users/status",
            data=urllib.parse.urlencode({"account_id": customer_id, "status": "disabled"}).encode("utf-8"),
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
        self.assertEqual(account["status"], "deleted")
        order = app.conn.execute("SELECT number, customer_account_id FROM b2b_orders WHERE number = 'B2B-ADMIN'").fetchone()
        self.assertEqual(order["customer_account_id"], customer_id)


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
                "enabled_password_reset": "on",
                "subject_password_reset": "Reset custom",
                "enabled_order_created": "on",
                "subject_order_created": "Order custom",
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

        reset = urllib.request.Request(
            base + "/admin/email/manual-reset",
            data=urllib.parse.urlencode({"customer_ref": "mail-admin@example.com"}).encode("utf-8"),
            headers={"Cookie": admin_cookie, "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        self.assertEqual(open_without_redirects(reset).status, 303)
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
                "business_min_order_amount_minor": "2500000",
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
        self.assertEqual(content["business"]["business_min_order_amount_minor"], "2500000")
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
        self.assertIn("color:#C7B166", contacts_html)
        self.assertIn("color:#F6F1E3", contacts_html)
        self.assertNotIn("<span>Адрес</span>", contacts_html)
        self.assertIn("map-info", contacts_html)
        self.assertIn("contacts-info-card", contacts_html)
        self.assertNotIn("<h1>Контакты</h1>", contacts_html)
        self.assertIn("grid-template-columns:minmax(0,430px) minmax(280px,.72fr)", contacts_html)
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
        self.assertIn("GOLD", html)
        self.assertIn("/media/custom-logo.svg", html)
        self.assertIn("Fresh release", html)
        self.assertIn("New lager batch is ready.", html)
        self.assertIn("/media/news.jpg", html)
        self.assertIn("/business/catalog", html)
        self.assertIn("Order now", html)
        self.assertIn("/media/taproom-bg.jpg", html)
        self.assertIn("--home-content-bg:url", html)
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
        self.assertIn("background:var(--golden-malt); color:var(--ink)", html)
        self.assertIn(".nav-icon img { width:100%; height:100%; padding:0; object-fit:contain", html)
        self.assertNotIn("nav-icon--cart", html)
        self.assertNotIn("news-card__label", html)
        self.assertNotIn("news-card__cta", html)
        self.assertIn("Beer list", html)
        self.assertIn("https://untappd.com/stamm", html)
        self.assertIn("/media/untappd.svg", html)
        self.assertIn("Вам есть 18+?", html)
        self.assertIn("Сайт содержит информацию о продукции, предназначенной для лиц старше 18 лет", html)
        self.assertIn("Да, мне есть 18", html)
        self.assertIn("Нет, мне нет 18", html)
        self.assertIn("window.history.back()", html)
        self.assertIn("about:blank", html)
        self.assertIn("stamm_age_confirmed", html)

    def test_beer_page_content_is_cms_managed(self) -> None:
        app = self.make_app()
        save_public_content(
            app.conn,
            {
                "beer_partners_title": "Где найти Stamm Brewing",
                "beer_partners_description": "Партнёры\nи бары",
                "beer_partners_is_visible": "1",
                "beer_partner_name_0": "Bottle Shop",
                "beer_partner_logo_url_0": "/media/partner.svg",
                "beer_partner_url_0": "https://partner.test",
                "beer_partner_size_0": "large",
                "beer_partner_sort_order_0": "10",
                "beer_partner_visible_0": "1",
                "beer_products_title": "Наша продукция",
                "beer_new_title": "Новинки",
                "beer_seasonal_title": "Сезонные сорта",
                "beer_products_is_visible": "1",
                "beer_new_is_visible": "1",
                "beer_seasonal_is_visible": "1",
                "beer_product_name_0": "Stamm IPA",
                "beer_product_style_0": "IPA",
                "beer_product_abv_0": "6.5%",
                "beer_product_image_url_0": "/media/ipa.png",
                "beer_product_untappd_url_0": "https://untappd.com/b/stamm-ipa",
                "beer_product_untappd_logo_url_0": "/media/untappd.svg",
                "beer_product_category_0": "new",
                "beer_product_sort_order_0": "10",
                "beer_product_visible_0": "1",
                "beer_product_name_1": "Stamm Saison",
                "beer_product_style_1": "Saison",
                "beer_product_abv_1": "5.2%",
                "beer_product_image_url_1": "/media/saison.png",
                "beer_product_category_1": "seasonal",
                "beer_product_sort_order_1": "20",
                "beer_product_visible_1": "1",
            },
        )
        content = get_public_site_content(app.conn)
        self.assertEqual(content["beer"]["partners"][0]["name"], "Bottle Shop")
        html = beer_page(content)
        self.assertIn("Где найти Stamm Brewing", html)
        self.assertIn("Партнёры\nи бары", html)
        self.assertIn('target="_blank"', html)
        self.assertIn("--logo-size:154px", html)
        self.assertIn("width:max-content", html)
        self.assertIn(".partner-card:hover img", html)
        self.assertNotIn("min-height:132px", html)
        self.assertIn("beer-can--featured", html)
        self.assertIn("beer-can--seasonal", html)
        self.assertIn("beer-modal", html)
        self.assertIn("beer-modal__mockup", html)
        self.assertIn("rgba(11,63,64,.30)", html)
        self.assertIn("style.textContent = data.style || ''", html)
        self.assertNotIn(">Stamm IPA</span>", html)
        self.assertIn("https://untappd.com/b/stamm-ipa", html)


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
            field("business_min_order_amount_minor", "2500000"),
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
            field("menu_beer_label", "Пиво"), field("menu_beer_sort_order", "10"), field("menu_beer_visible", "on"),
            field("menu_visit_label", "Посетить пивоварню"), field("menu_visit_sort_order", "20"), field("menu_visit_visible", "on"),
            field("menu_history_label", "История"), field("menu_history_sort_order", "30"), field("menu_history_visible", "on"),
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
        tg = next(item for item in content["actions"] if item["key"] == "tg")
        self.assertTrue(tg["icon_url"].startswith("/media/nav-tg-"))
        self.assertIn(content["home"]["home_logo_url"], home_page(content))
        self.assertIn(content["home"]["home_news_image_url"], home_page(content))
        self.assertIn(content["home"]["home_content_bg_url"], home_page(content))
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
        self.assertEqual(kegs["items"][0]["orderRules"]["step"], 1)
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
        self.assertIn("normalizeQuantity", html)
        self.assertIn("submitOrder", html)
        self.assertIn("/api/public/business/order", html)
        self.assertIn("Вам есть 18+?", html)
        self.assertIn("stamm_age_confirmed", html)
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
        self.assertNotIn('href="/">Главная</a>', home_html)

        for path in ("/business", "/business/catalog"):
            response = urllib.request.urlopen(base + path, timeout=5)
            self.assertEqual(response.status, 200)
            body = response.read().decode("utf-8")
            self.assertIn("Корзина", body)
            self.assertNotIn("<h1>БИЗНЕС</h1>", body)

        redirects = {"/business/": "/business", "/business/catalog/": "/business/catalog"}
        for path, expected_location in redirects.items():
            response = open_without_redirects(base + path)
            self.assertEqual(response.status, 303)
            self.assertEqual(response.headers["Location"], expected_location)

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
        self.assertEqual(data["meta"]["minimumOrder"]["amountMinor"], 1500000)

    def test_public_business_order_api_enforces_minimum_and_can_boxes(self) -> None:
        app = self.make_app()
        keg_id = self.add_catalog_item(app, "Stamm IPA Keg", "keg", "stamm-ipa-keg")
        can_id = self.add_catalog_item(app, "Stamm Pale Ale 0,45 Can", "keg", "stamm-pale-ale-can")
        can_href = "https://api.moysklad.ru/api/remap/1.2/entity/product/can-1"
        app.conn.execute("UPDATE business_catalog_items SET price_minor = 500000 WHERE product_id IN (?, ?)", (keg_id, can_id))
        app.conn.execute("UPDATE products SET external_href = ? WHERE id = ?", (can_href, can_id))
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
        self.assertEqual(app.conn.execute("SELECT COUNT(*) FROM moysklad_sync_logs").fetchone()[0], 5)

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

        server = ThreadingHTTPServer(("127.0.0.1", 0), app.handler_class())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"

        request = urllib.request.Request(base + "/account", headers={"Cookie": cookie})
        page_html = urllib.request.urlopen(request, timeout=5).read().decode("utf-8")
        self.assertIn("ООО Штамм Партнёр", page_html)
        self.assertIn("Контрагент МойСклад найден", page_html)
        self.assertIn("Диагностика скидки МойСклад", page_html)

        anonymous = open_without_redirects(base + "/account")
        self.assertEqual(anonymous.code, 303)
        self.assertEqual(anonymous.headers["Location"], "/account/login")

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

        guest = json.loads(urllib.request.urlopen(base + "/api/public/business/catalog", timeout=5).read().decode("utf-8"))
        request_a = urllib.request.Request(base + "/api/public/business/catalog", headers={"Cookie": f"stamm_customer_session={session_a}"})
        request_b = urllib.request.Request(base + "/api/public/business/catalog", headers={"Cookie": f"stamm_customer_session={session_b}"})
        response_a = json.loads(urllib.request.urlopen(request_a, timeout=5).read().decode("utf-8"))
        response_b = json.loads(urllib.request.urlopen(request_b, timeout=5).read().decode("utf-8"))

        self.assertEqual(guest["items"][0]["price"]["amountMinor"], 12300)
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
