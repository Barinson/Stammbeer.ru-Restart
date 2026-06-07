from __future__ import annotations

import json
import mimetypes
import sqlite3
import urllib.parse
import uuid
from pathlib import Path
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.config import Settings, load_settings
from app.db.connection import connect
from app.db.migrations import run_migrations
from app.db.seed import seed_core
from app.integrations.moysklad.catalog_sync import latest_sync_diagnostics, run_manual_catalog_sync
from app.integrations.moysklad.settings_service import (
    get_settings,
    refresh_integration_references,
    save_settings,
    serialize_settings,
    test_saved_connection,
)
from app.modules.admin.views import admin_catalog_page, content_management_page, dashboard, login_page, moysklad_settings_page, page, placeholder, profile_page
from app.modules.catalog.service import admin_catalog_items, public_catalog, publish_product
from app.modules.account.service import (
    authenticate_customer,
    create_customer_session,
    current_customer,
    customer_cookie_header,
    customer_session_from_cookie,
    destroy_customer_session,
    expired_customer_cookie_header,
    register_customer,
)
from app.modules.content.service import ensure_public_content_defaults, get_public_site_content, save_public_content
from app.modules.public_views import (
    account_dashboard_page,
    account_login_page,
    account_register_page,
    business_storefront_page,
    home_page,
    public_placeholder_page,
)
from app.modules.auth.service import (
    authenticate,
    change_password,
    cookie_header,
    create_session,
    current_user,
    destroy_session,
    expired_cookie_header,
    require_permission,
    session_from_cookie,
)

BUSINESS_STOREFRONT_ROUTES = {"/business", "/business/catalog"}
BUSINESS_STOREFRONT_REDIRECTS = {"/business/": "/business", "/business/catalog/": "/business/catalog"}
PUBLIC_PLACEHOLDER_ROUTES = {
    "/beer": ("Пиво", "beer"),
    "/visit": ("Посетить пивоварню", "visit"),
    "/history": ("История", "history"),
    "/contacts": ("Контакты", "contacts"),
}
PUBLIC_CATALOG_API_ROUTE = "/api/public/business/catalog"


def parse_form(body: bytes) -> dict[str, Any]:
    parsed = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


class StammApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn = connect(settings.sqlite_path)
        run_migrations(self.conn)
        seed_core(self.conn, settings.admin_email, settings.admin_password)
        ensure_public_content_defaults(self.conn)

    def handler_class(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                if app.settings.env != "test":
                    super().log_message(format, *args)

            def send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK, headers: dict[str, str] | None = None) -> None:
                payload = html.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)

            def send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
                payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def send_bytes(self, payload: bytes, content_type: str = "application/octet-stream", status: HTTPStatus = HTTPStatus.OK) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def redirect(self, location: str, headers: dict[str, str] | None = None) -> None:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", location)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()

            def read_form(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                return parse_form(self.rfile.read(length))

            def read_multipart_form(self) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
                content_type = self.headers.get("Content-Type", "")
                marker = "boundary="
                if marker not in content_type:
                    return self.read_form(), {}
                boundary = content_type.split(marker, 1)[1].strip().strip('"').encode("utf-8")
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                fields: dict[str, Any] = {}
                files: dict[str, dict[str, Any]] = {}
                for raw_part in body.split(b"--" + boundary):
                    raw_part = raw_part.strip(b"\r\n")
                    if not raw_part or raw_part == b"--" or b"\r\n\r\n" not in raw_part:
                        continue
                    header_bytes, value = raw_part.split(b"\r\n\r\n", 1)
                    headers = header_bytes.decode("utf-8", "ignore")
                    disposition = next((line for line in headers.split("\r\n") if line.lower().startswith("content-disposition")), "")
                    if 'name="' not in disposition:
                        continue
                    name = disposition.split('name="', 1)[1].split('"', 1)[0]
                    value = value.rstrip(b"\r\n")
                    if 'filename="' in disposition:
                        filename = disposition.split('filename="', 1)[1].split('"', 1)[0]
                        if filename and value:
                            files[name] = {"filename": filename, "content": value, "content_type": "application/octet-stream"}
                    else:
                        fields[name] = value.decode("utf-8", "ignore")
                return fields, files

            def save_uploaded_media(self, upload: dict[str, Any], prefix: str) -> str:
                media_dir = Path("var/media")
                media_dir.mkdir(parents=True, exist_ok=True)
                original = Path(str(upload["filename"])).name.replace(" ", "-")
                suffix = Path(original).suffix.lower() or ".bin"
                safe_name = f"{prefix}-{uuid.uuid4().hex[:10]}{suffix}"
                target = media_dir / safe_name
                target.write_bytes(upload["content"])
                return "/media/" + safe_name

            def admin_user(self) -> sqlite3.Row | None:
                return current_user(app.conn, self.headers.get("Cookie"))

            def require_admin(self) -> sqlite3.Row | None:
                user = self.admin_user()
                if user is None:
                    self.redirect("/admin/login")
                return user

            def do_GET(self) -> None:  # noqa: N802
                path = urllib.parse.urlparse(self.path).path
                if path == "/healthz":
                    self.send_json({"ok": True, "app": app.settings.app_name})
                    return
                if path.startswith("/media/"):
                    media_path = Path("var/media") / path.removeprefix("/media/")
                    if media_path.exists() and media_path.is_file() and media_path.resolve().is_relative_to(Path("var/media").resolve()):
                        self.send_bytes(media_path.read_bytes(), mimetypes.guess_type(str(media_path))[0] or "application/octet-stream")
                    else:
                        self.send_html(page("404", "<main class='login'><div class='card'>Файл не найден.</div></main>"), HTTPStatus.NOT_FOUND)
                    return
                if path == "/":
                    self.send_html(home_page(get_public_site_content(app.conn)))
                    return
                if path in PUBLIC_PLACEHOLDER_ROUTES:
                    title, active = PUBLIC_PLACEHOLDER_ROUTES[path]
                    self.send_html(public_placeholder_page(title, active, get_public_site_content(app.conn)))
                    return
                if path in BUSINESS_STOREFRONT_REDIRECTS:
                    self.redirect(BUSINESS_STOREFRONT_REDIRECTS[path])
                    return
                if path in BUSINESS_STOREFRONT_ROUTES:
                    self.send_html(business_storefront_page(get_public_site_content(app.conn)))
                    return
                if path == PUBLIC_CATALOG_API_ROUTE:
                    query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                    catalog = public_catalog(app.conn, query.get("containerType", [None])[0])
                    self.send_json(catalog)
                    return
                if path == "/account/register":
                    self.send_html(account_register_page(get_public_site_content(app.conn)))
                    return
                if path == "/account/login":
                    self.send_html(account_login_page(get_public_site_content(app.conn)))
                    return
                if path == "/account":
                    customer = current_customer(app.conn, self.headers.get("Cookie"))
                    if customer is None:
                        self.redirect("/account/login")
                        return
                    self.send_html(account_dashboard_page(customer, get_public_site_content(app.conn)))
                    return
                if path == "/admin/login":
                    self.send_html(login_page())
                    return
                if path == "/admin/logout":
                    destroy_session(app.conn, session_from_cookie(self.headers.get("Cookie")))
                    self.redirect("/admin/login", {"Set-Cookie": expired_cookie_header()})
                    return
                if path.startswith("/admin"):
                    user = self.require_admin()
                    if user is None:
                        return
                    if path == "/admin":
                        stats = admin_stats(app.conn)
                        self.send_html(dashboard(user["email"], stats))
                        return
                    if path == "/admin/catalog":
                        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        self.send_html(admin_catalog_page(user["email"], admin_catalog_items(app.conn), result=query.get("result", [None])[0], error=query.get("error", [None])[0]))
                        return
                    if path == "/admin/moysklad":
                        if not require_permission(app.conn, user, "moysklad.read"):
                            self.send_html(page("Нет доступа", "<div class='card'>Недостаточно прав.</div>", user["email"]), HTTPStatus.FORBIDDEN)
                            return
                        settings = serialize_settings(get_settings(app.conn))
                        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        self.send_html(moysklad_settings_page(user["email"], settings, result=query.get("result", [None])[0], error=query.get("error", [None])[0], diagnostics=latest_sync_diagnostics(app.conn)))
                        return
                    if path == "/admin/b2b-orders":
                        self.send_html(placeholder("B2B-заявки", "Здесь будет список заявок, статусы, детали и заметки менеджера.", user["email"]))
                        return
                    if path == "/admin/content":
                        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        self.send_html(content_management_page(user["email"], get_public_site_content(app.conn, include_hidden=True), result=query.get("result", [None])[0], error=query.get("error", [None])[0]))
                        return
                    if path == "/admin/users":
                        self.send_html(placeholder("Пользователи и роли", "Здесь будут пользователи, роли, permissions и журнал действий.", user["email"]))
                        return
                    if path == "/admin/profile":
                        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        self.send_html(profile_page(user["email"], result=query.get("result", [None])[0], error=query.get("error", [None])[0]))
                        return
                self.send_html(page("404", "<main class='login'><div class='card'>Страница не найдена.</div></main>"), HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:  # noqa: N802
                path = urllib.parse.urlparse(self.path).path
                if path == "/account/register":
                    form = self.read_form()
                    result = register_customer(
                        app.conn,
                        form.get("inn", ""),
                        form.get("email", ""),
                        form.get("password", ""),
                        form.get("password_confirm", ""),
                    )
                    if not result.ok or result.account is None:
                        self.send_html(
                            account_register_page(
                                get_public_site_content(app.conn),
                                error=result.message,
                                values={"inn": form.get("inn", ""), "email": form.get("email", "")},
                            ),
                            HTTPStatus.BAD_REQUEST,
                        )
                        return
                    session_id = create_customer_session(app.conn, result.account["id"])
                    self.redirect("/account", {"Set-Cookie": customer_cookie_header(session_id)})
                    return
                if path == "/account/login":
                    form = self.read_form()
                    customer = authenticate_customer(app.conn, form.get("email", ""), form.get("password", ""))
                    if customer is None:
                        self.send_html(
                            account_login_page(
                                get_public_site_content(app.conn),
                                error="Неверный e-mail или пароль.",
                                values={"email": form.get("email", "")},
                            ),
                            HTTPStatus.UNAUTHORIZED,
                        )
                        return
                    session_id = create_customer_session(app.conn, customer["id"])
                    self.redirect("/account", {"Set-Cookie": customer_cookie_header(session_id)})
                    return
                if path == "/account/logout":
                    destroy_customer_session(app.conn, customer_session_from_cookie(self.headers.get("Cookie")))
                    self.redirect("/account/login", {"Set-Cookie": expired_customer_cookie_header()})
                    return
                if path == "/admin/login":
                    form = self.read_form()
                    user = authenticate(app.conn, form.get("email", ""), form.get("password", ""))
                    if user is None:
                        self.send_html(login_page("Неверный email или пароль"), HTTPStatus.UNAUTHORIZED)
                        return
                    session_id = create_session(app.conn, user["id"])
                    self.redirect("/admin", {"Set-Cookie": cookie_header(session_id)})
                    return
                if path in {"/admin/moysklad/save", "/admin/moysklad/test", "/admin/moysklad/sync-products"}:
                    user = self.require_admin()
                    if user is None:
                        return
                    permission = "moysklad.write_settings"
                    if not require_permission(app.conn, user, permission):
                        self.send_html(page("Нет доступа", "<div class='card'>Недостаточно прав.</div>", user["email"]), HTTPStatus.FORBIDDEN)
                        return
                    form = self.read_form()
                    data = {
                        "api_base_url": form.get("api_base_url"),
                        "token": form.get("token"),
                        "store_href": form.get("store_href"),
                        "source_product_folder_href": form.get("source_product_folder_href"),
                        "include_child_folders": "include_child_folders" in form,
                        "full_sync_interval_minutes": form.get("full_sync_interval_minutes"),
                        "stock_sync_interval_minutes": form.get("stock_sync_interval_minutes"),
                        "is_enabled": "is_enabled" in form,
                    }
                    save_settings(app.conn, data, user["id"])
                    if path == "/admin/moysklad/test":
                        result = test_saved_connection(app.conn)
                        if result.ok:
                            try:
                                counts = refresh_integration_references(app.conn)
                                message = f"{result.message}. Загружено складов: {counts['stores']}, папок: {counts['folders']}"
                                self.redirect("/admin/moysklad?result=" + urllib.parse.quote(message))
                            except Exception as exc:
                                message = f"{result.message}, но не удалось загрузить склады/папки: {exc}"
                                self.redirect("/admin/moysklad?error=" + urllib.parse.quote(message))
                        else:
                            self.redirect("/admin/moysklad?error=" + urllib.parse.quote(result.message))
                        return
                    if path == "/admin/moysklad/sync-products":
                        try:
                            result = run_manual_catalog_sync(app.conn, user["id"], diagnostic_mode="diagnostic_mode" in form)
                            stats = result["stats"]
                            message = f"Sync завершён: найдено {stats['found']}, создано {stats['created']}, обновлено {stats['updated']}"
                            self.redirect("/admin/moysklad?result=" + urllib.parse.quote(message))
                        except Exception as exc:
                            self.redirect("/admin/moysklad?error=" + urllib.parse.quote(str(exc)))
                        return
                    self.redirect("/admin/moysklad?result=" + urllib.parse.quote("Настройки сохранены"))
                    return
                if path == "/admin/content/save":
                    user = self.require_admin()
                    if user is None:
                        return
                    if not require_permission(app.conn, user, "content.write"):
                        self.send_html(page("Нет доступа", "<div class='card'>Недостаточно прав.</div>", user["email"]), HTTPStatus.FORBIDDEN)
                        return
                    form, files = self.read_multipart_form()
                    logo_file = files.get("home_logo_file")
                    if logo_file:
                        form["home_logo_url"] = self.save_uploaded_media(logo_file, "home-logo")
                    content_bg_file = files.get("home_content_bg_file")
                    if content_bg_file:
                        form["home_content_bg_url"] = self.save_uploaded_media(content_bg_file, "home-content-bg")
                    news_file = files.get("home_news_image_file")
                    if news_file:
                        form["home_news_image_url"] = self.save_uploaded_media(news_file, "home-news")
                    for field_name, upload in files.items():
                        if field_name.startswith("action_") and field_name.endswith("_icon_file"):
                            key = field_name.removeprefix("action_").removesuffix("_icon_file")
                            form[f"action_{key}_icon_url"] = self.save_uploaded_media(upload, f"nav-{key}")
                    save_public_content(app.conn, form)
                    self.redirect("/admin/content?result=" + urllib.parse.quote("Контент сохранён"))
                    return
                if path == "/admin/catalog/publication":
                    user = self.require_admin()
                    if user is None:
                        return
                    form = self.read_form()
                    publish_product(app.conn, int(form.get("product_id", "0")), form.get("publish") == "1")
                    self.redirect("/admin/catalog?result=" + urllib.parse.quote("Статус публикации обновлён"))
                    return
                if path == "/admin/profile/password":
                    user = self.require_admin()
                    if user is None:
                        return
                    form = self.read_form()
                    new_password = form.get("new_password", "")
                    confirm = form.get("new_password_confirm", "")
                    if new_password != confirm:
                        self.redirect("/admin/profile?error=" + urllib.parse.quote("Новый пароль и подтверждение не совпадают"))
                        return
                    ok, message = change_password(app.conn, user["id"], form.get("current_password", ""), new_password)
                    query_key = "result" if ok else "error"
                    self.redirect(f"/admin/profile?{query_key}=" + urllib.parse.quote(message))
                    return
                self.send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

        return Handler


def admin_stats(conn: sqlite3.Connection) -> dict[str, object]:
    return {
        "Опубликованные SKU": conn.execute("SELECT COUNT(*) FROM product_overrides WHERE is_published = 1").fetchone()[0],
        "Скрытые SKU": conn.execute("SELECT COUNT(*) FROM product_overrides WHERE is_published = 0").fetchone()[0],
        "Sync jobs": conn.execute("SELECT COUNT(*) FROM moysklad_sync_jobs").fetchone()[0],
        "B2B-заявки": conn.execute("SELECT COUNT(*) FROM b2b_orders").fetchone()[0],
        "Статус sync": "foundation ready",
    }


def main() -> None:
    settings = load_settings()
    app = StammApp(settings)
    server = ThreadingHTTPServer((settings.host, settings.port), app.handler_class())
    print(f"{settings.app_name} listening on http://{settings.host}:{settings.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
