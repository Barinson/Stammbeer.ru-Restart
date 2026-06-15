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
from app.integrations.moysklad.catalog_sync import infer_container_type, latest_sync_diagnostics, run_manual_catalog_sync
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
from app.main import StammApp, admin_stats
from app.modules.catalog.service import admin_catalog_items, public_catalog, publish_product
from app.modules.content.service import get_public_site_content, save_public_content
from app.modules.public_views import business_storefront_page, home_page
from app.modules.auth.service import authenticate, change_password, create_session, current_user


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

    def test_moysklad_container_inference_treats_liter_s_a_skus_as_kegs(self) -> None:
        self.assertEqual(infer_container_type({"name": "Stamm Lager 10л (S)", "article": "LAGER-S"}), "keg")
        self.assertEqual(infer_container_type({"name": "Stamm IPA 20л (A)", "code": "IPA-A"}), "keg")

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
        self.add_catalog_item(app, "Stamm Pale Ale Can", "can", "stamm-pale-ale-can")
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
        self.assertIn("Оформить заявку", html)
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
                            "salePrices": [
                                {"value": 999, "priceType": {"name": "Закупочная цена"}},
                                {"value": 12345, "priceType": {"name": "Цена продажи"}},
                            ],
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
        self.assertFalse(products[0]["is_published"])
        unavailable_id = app.conn.execute(
            """
            INSERT INTO products (accounting_name, external_href, stock_quantity, availability_status, sync_state)
            VALUES ('Unavailable stale SKU', 'stale-zero', 0, 'unavailable', 'out_of_stock')
            """
        ).lastrowid
        with self.assertRaises(ValueError):
            publish_product(app.conn, unavailable_id, True)
        self.assertEqual(app.conn.execute("SELECT COUNT(*) FROM business_catalog_items").fetchone()[0], 0)
        self.assertEqual(app.conn.execute("SELECT COUNT(*) FROM moysklad_sync_jobs WHERE status = 'success'").fetchone()[0], 2)
        self.assertEqual(app.conn.execute("SELECT COUNT(*) FROM moysklad_sync_logs").fetchone()[0], 5)

        publish_product(app.conn, products[0]["id"], True)
        self.assertEqual(app.conn.execute("SELECT COUNT(*) FROM business_catalog_items").fetchone()[0], 1)
        public_item = public_catalog(app.conn)["items"][0]
        self.assertEqual(public_item["imageUrl"], "https://cdn.example.test/moysklad/ipa-mini.jpg")


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
                            "name": "Nested IPA can",
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
        self.assertTrue(catalog["items"][0]["price"]["isPersonalized"])

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


if __name__ == "__main__":
    unittest.main()
