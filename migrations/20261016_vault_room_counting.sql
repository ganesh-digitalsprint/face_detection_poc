ALTER TABLE vault_room_sessions
    ADD COLUMN IF NOT EXISTS peak_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS seconds_at_count JSON NOT NULL DEFAULT '{"0":0,"1":0,"2":0,"3_plus":0}',
    ADD COLUMN IF NOT EXISTS alert_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS count_at_expiry INTEGER NULL,
    ADD COLUMN IF NOT EXISTS count_at_close INTEGER NULL;

CREATE TABLE IF NOT EXISTS vault_room_alerts (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    type VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    message TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ NULL,
    count_at_open INTEGER NULL,
    expected INTEGER NULL,
    duration_seconds DOUBLE PRECISION NULL
);
CREATE INDEX IF NOT EXISTS ix_vault_room_alerts_session_id ON vault_room_alerts (session_id);
