CREATE TABLE IF NOT EXISTS vault_room_sessions (
    id VARCHAR(36) PRIMARY KEY,
    dual_control_session_id VARCHAR(128) NOT NULL,
    employees JSON NOT NULL,
    required_persons INTEGER NOT NULL,
    test_mode BOOLEAN NOT NULL,
    granted_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NULL,
    ended_at TIMESTAMPTZ NOT NULL,
    end_reason VARCHAR(64) NOT NULL,
    duration_seconds INTEGER NOT NULL,
    expired_before_close BOOLEAN NOT NULL,
    expired_alert_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vault_room_sessions_dual_control_session_id
    ON vault_room_sessions (dual_control_session_id);

CREATE TABLE IF NOT EXISTS vault_room_events (
    id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    type VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    message TEXT NOT NULL,
    data JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vault_room_events_session_id ON vault_room_events (session_id);
