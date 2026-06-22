CREATE TABLE IF NOT EXISTS email_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    provider TEXT NOT NULL DEFAULT 'yandex',
    is_enabled INTEGER NOT NULL DEFAULT 0,
    smtp_host TEXT NOT NULL DEFAULT 'smtp.yandex.com',
    smtp_port INTEGER NOT NULL DEFAULT 465,
    smtp_username TEXT,
    smtp_password_secret TEXT,
    from_email TEXT,
    from_name TEXT NOT NULL DEFAULT 'Stamm Brewing',
    reply_to_email TEXT,
    use_ssl INTEGER NOT NULL DEFAULT 1,
    use_tls INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS email_templates (
    message_type TEXT PRIMARY KEY,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    subject TEXT NOT NULL,
    body_text TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
