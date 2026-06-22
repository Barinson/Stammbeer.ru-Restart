ALTER TABLE moysklad_sync_settings ADD COLUMN store_id TEXT;
ALTER TABLE moysklad_sync_settings ADD COLUMN store_href TEXT;
ALTER TABLE moysklad_sync_settings ADD COLUMN store_name TEXT;
ALTER TABLE moysklad_sync_settings ADD COLUMN source_product_folder_id TEXT;
ALTER TABLE moysklad_sync_settings ADD COLUMN source_product_folder_name TEXT;
ALTER TABLE moysklad_sync_settings ADD COLUMN available_stores_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE moysklad_sync_settings ADD COLUMN available_product_folders_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE moysklad_sync_settings ADD COLUMN references_loaded_at TEXT;
