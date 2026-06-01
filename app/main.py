from __future__ import annotations

import json
import sqlite3
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.config import Settings, load_settings
from app.db.connection import connect
from app.db.migrations import run_migrations
from app.db.seed import seed_core
from app.integrations.moysklad.settings_service import (
    get_settings,
    save_settings,
    serialize_settings,
    test_saved_connection,
)
from app.modules.admin.views import dashboard, login_page, moysklad_settings_page, page, placeholder, profile_page
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


def parse_form(body: bytes) -> dict[str, Any]:
    parsed = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


class StammApp:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.conn = connect(settings.sqlite_path)
        run_migrations(self.conn)
        seed_core(self.conn, settings.admin_email, settings.admin_password)

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

            def redirect(self, location: str, headers: dict[str, str] | None = None) -> None:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", location)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()

            def read_form(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                return parse_form(self.rfile.read(length))

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
                if path == "/":
                    self.send_html(page("Stamm Brewing", "<main class='login'><div class='card'><h1>Stamm Brewing</h1><p>Public frontend foundation. B2B catalog will read only local DB/read-model.</p><p><a class='button' href='/admin'>Admin</a></p></div></main>"))
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
                        self.send_html(placeholder("Каталог", "Здесь появятся локальные товары, override-поля, публикация и сортировка.", user["email"]))
                        return
                    if path == "/admin/moysklad":
                        if not require_permission(app.conn, user, "moysklad.read"):
                            self.send_html(page("Нет доступа", "<div class='card'>Недостаточно прав.</div>", user["email"]), HTTPStatus.FORBIDDEN)
                            return
                        settings = serialize_settings(get_settings(app.conn))
                        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                        self.send_html(moysklad_settings_page(user["email"], settings, result=query.get("result", [None])[0], error=query.get("error", [None])[0]))
                        return
                    if path == "/admin/b2b-orders":
                        self.send_html(placeholder("B2B-заявки", "Здесь будет список заявок, статусы, детали и заметки менеджера.", user["email"]))
                        return
                    if path == "/admin/content":
                        self.send_html(placeholder("Контент", "Здесь будут страницы сайта, баннеры, тексты, медиа и SEO.", user["email"]))
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
                if path == "/admin/login":
                    form = self.read_form()
                    user = authenticate(app.conn, form.get("email", ""), form.get("password", ""))
                    if user is None:
                        self.send_html(login_page("Неверный email или пароль"), HTTPStatus.UNAUTHORIZED)
                        return
                    session_id = create_session(app.conn, user["id"])
                    self.redirect("/admin", {"Set-Cookie": cookie_header(session_id)})
                    return
                if path in {"/admin/moysklad/save", "/admin/moysklad/test"}:
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
                            self.redirect("/admin/moysklad?result=" + urllib.parse.quote(result.message))
                        else:
                            self.redirect("/admin/moysklad?error=" + urllib.parse.quote(result.message))
                        return
                    self.redirect("/admin/moysklad?result=" + urllib.parse.quote("Настройки сохранены"))
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
