from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from app.modules.auth.security import hash_password, new_session_id, verify_password

SESSION_COOKIE = "stamm_admin_session"
SESSION_DAYS = 7


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def authenticate(conn: sqlite3.Connection, email: str, password: str) -> sqlite3.Row | None:
    user = conn.execute(
        "SELECT * FROM users WHERE lower(email) = lower(?) AND status = 'active'",
        (email.strip(),),
    ).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        return None
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (iso(utc_now()), user["id"]))
    conn.commit()
    return user


def change_password(conn: sqlite3.Connection, user_id: int, current_password: str, new_password: str) -> tuple[bool, str]:
    user = conn.execute("SELECT * FROM users WHERE id = ? AND status = 'active'", (user_id,)).fetchone()
    if not user or not verify_password(current_password, user["password_hash"]):
        return False, "Текущий пароль указан неверно"
    if len(new_password) < 1:
        return False, "Новый пароль не может быть пустым"
    conn.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (hash_password(new_password), iso(utc_now()), user_id))
    conn.commit()
    return True, "Пароль обновлён"


def create_session(conn: sqlite3.Connection, user_id: int) -> str:
    session_id = new_session_id()
    expires_at = iso(utc_now() + timedelta(days=SESSION_DAYS))
    conn.execute(
        "INSERT INTO admin_sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
        (session_id, user_id, expires_at),
    )
    conn.commit()
    return session_id


def destroy_session(conn: sqlite3.Connection, session_id: str | None) -> None:
    if session_id:
        conn.execute("DELETE FROM admin_sessions WHERE id = ?", (session_id,))
        conn.commit()


def session_from_cookie(cookie_header: str | None) -> str | None:
    if not cookie_header:
        return None
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    morsel = cookie.get(SESSION_COOKIE)
    return morsel.value if morsel else None


def current_user(conn: sqlite3.Connection, cookie_header: str | None) -> sqlite3.Row | None:
    session_id = session_from_cookie(cookie_header)
    if not session_id:
        return None
    row = conn.execute(
        """
        SELECT users.*
        FROM admin_sessions
        JOIN users ON users.id = admin_sessions.user_id
        WHERE admin_sessions.id = ?
          AND admin_sessions.expires_at > ?
          AND users.status = 'active'
        """,
        (session_id, iso(utc_now())),
    ).fetchone()
    if row:
        conn.execute("UPDATE admin_sessions SET last_seen_at = ? WHERE id = ?", (iso(utc_now()), session_id))
        conn.commit()
    return row


def user_permissions(conn: sqlite3.Connection, user_id: int) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT permissions.code
        FROM permissions
        JOIN role_permissions ON role_permissions.permission_id = permissions.id
        JOIN user_roles ON user_roles.role_id = role_permissions.role_id
        WHERE user_roles.user_id = ?
        """,
        (user_id,),
    ).fetchall()
    return {row[0] for row in rows}


def require_permission(conn: sqlite3.Connection, user: sqlite3.Row, permission: str) -> bool:
    return permission in user_permissions(conn, user["id"])


def cookie_header(session_id: str) -> str:
    return f"{SESSION_COOKIE}={session_id}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_DAYS * 24 * 60 * 60}"


def expired_cookie_header() -> str:
    return f"{SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"
