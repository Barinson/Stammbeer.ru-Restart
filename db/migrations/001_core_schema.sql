CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT
);

CREATE TABLE permissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE user_roles (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE admin_sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    before_json TEXT,
    after_json TEXT,
    ip TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE seo_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meta_title TEXT,
    meta_description TEXT,
    canonical_url TEXT,
    og_title TEXT,
    og_description TEXT,
    og_image_id INTEGER,
    robots TEXT DEFAULT 'index,follow'
);

CREATE TABLE media_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    storage_key TEXT NOT NULL,
    url TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    alt TEXT,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE content_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    template TEXT NOT NULL DEFAULT 'default',
    seo_metadata_id INTEGER REFERENCES seo_metadata(id) ON DELETE SET NULL,
    published_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE moysklad_sync_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    api_base_url TEXT NOT NULL,
    encrypted_token TEXT,
    token_hint TEXT,
    source_product_folder_href TEXT,
    include_child_folders INTEGER NOT NULL DEFAULT 1,
    store_external_ids_json TEXT NOT NULL DEFAULT '[]',
    price_type_external_id TEXT,
    full_sync_interval_minutes INTEGER NOT NULL DEFAULT 360,
    stock_sync_interval_minutes INTEGER NOT NULL DEFAULT 120,
    is_enabled INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT,
    last_error_at TEXT,
    last_known_good_job_id INTEGER,
    updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE moysklad_sync_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    trigger_source TEXT NOT NULL DEFAULT 'manual',
    started_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    started_at TEXT,
    finished_at TEXT,
    lock_key TEXT,
    stats_json TEXT NOT NULL DEFAULT '{}',
    error_summary TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE moysklad_sync_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES moysklad_sync_jobs(id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    stage TEXT NOT NULL,
    entity_type TEXT,
    external_href TEXT,
    message TEXT NOT NULL,
    error_code TEXT,
    payload_excerpt_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE catalog_folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT UNIQUE,
    external_href TEXT UNIQUE,
    parent_id INTEGER REFERENCES catalog_folders(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    path TEXT,
    is_in_source_scope INTEGER NOT NULL DEFAULT 1,
    last_synced_at TEXT
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT UNIQUE,
    external_href TEXT UNIQUE,
    folder_id INTEGER REFERENCES catalog_folders(id) ON DELETE SET NULL,
    accounting_name TEXT NOT NULL,
    code TEXT,
    article TEXT,
    external_code TEXT,
    unit_name TEXT,
    is_archived INTEGER NOT NULL DEFAULT 0,
    sync_updated_at TEXT,
    last_synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE product_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    external_id TEXT UNIQUE,
    external_href TEXT UNIQUE,
    name TEXT NOT NULL,
    code TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    last_synced_at TEXT
);

CREATE TABLE product_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL UNIQUE REFERENCES products(id) ON DELETE CASCADE,
    public_name TEXT,
    slug TEXT UNIQUE,
    short_description TEXT,
    description TEXT,
    container_type_override TEXT,
    volume_liters_override REAL,
    is_published INTEGER NOT NULL DEFAULT 0,
    allow_preorder INTEGER NOT NULL DEFAULT 0,
    min_order_quantity INTEGER NOT NULL DEFAULT 1,
    order_step INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 1000,
    seo_metadata_id INTEGER REFERENCES seo_metadata(id) ON DELETE SET NULL,
    updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE inventory_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_job_id INTEGER REFERENCES moysklad_sync_jobs(id) ON DELETE SET NULL,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    variant_id INTEGER REFERENCES product_variants(id) ON DELETE CASCADE,
    store_external_id TEXT,
    stock REAL NOT NULL DEFAULT 0,
    reserve REAL NOT NULL DEFAULT 0,
    in_transit REAL NOT NULL DEFAULT 0,
    available_quantity REAL NOT NULL DEFAULT 0,
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE business_catalog_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    variant_id INTEGER REFERENCES product_variants(id) ON DELETE CASCADE,
    slug TEXT NOT NULL UNIQUE,
    public_name TEXT NOT NULL,
    image_url TEXT,
    price_minor INTEGER,
    currency TEXT DEFAULT 'RUB',
    container_type TEXT,
    volume_liters REAL,
    availability_status TEXT NOT NULL DEFAULT 'unavailable',
    sort_order INTEGER NOT NULL DEFAULT 1000,
    search_text TEXT NOT NULL DEFAULT '',
    last_catalog_sync_at TEXT
);

CREATE TABLE b2b_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'new',
    contact_name TEXT NOT NULL,
    company_name TEXT NOT NULL,
    inn TEXT,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    city TEXT NOT NULL,
    comment TEXT,
    total_minor INTEGER,
    currency TEXT DEFAULT 'RUB',
    source_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE b2b_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES b2b_orders(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    variant_id INTEGER REFERENCES product_variants(id) ON DELETE SET NULL,
    quantity REAL NOT NULL,
    price_minor INTEGER,
    line_total_minor INTEGER,
    product_snapshot_json TEXT NOT NULL,
    availability_snapshot_json TEXT NOT NULL DEFAULT '{}'
);
