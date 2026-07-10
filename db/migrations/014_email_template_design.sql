ALTER TABLE email_templates ADD COLUMN heading TEXT;
ALTER TABLE email_templates ADD COLUMN preheader_text TEXT;
ALTER TABLE email_templates ADD COLUMN footer_text TEXT;
ALTER TABLE email_templates ADD COLUMN image_url TEXT;
ALTER TABLE email_templates ADD COLUMN background_color TEXT;
ALTER TABLE email_templates ADD COLUMN background_image_url TEXT;
ALTER TABLE email_templates ADD COLUMN background_image_enabled INTEGER NOT NULL DEFAULT 0;
