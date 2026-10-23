-- Replace the authorization_status enum with a boolean is_active flag.
-- Existing ACTIVE rows become TRUE; every other prior state becomes FALSE.
BEGIN;

ALTER TABLE IF EXISTS authorized_employees
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'authorized_employees'
          AND column_name = 'authorization_status'
    ) THEN
        UPDATE authorized_employees
        SET is_active = (authorization_status::text = 'ACTIVE');
    END IF;
END
$$;

ALTER TABLE IF EXISTS authorized_employees
    DROP COLUMN IF EXISTS authorization_status;

DROP TYPE IF EXISTS authorization_status;

ALTER TABLE IF EXISTS authorized_employees
    DROP COLUMN IF EXISTS authorization_expires_at;

COMMIT;
