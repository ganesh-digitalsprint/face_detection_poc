-- Stage 3: persistent alert lifecycle, safe session references, and append-only audit.
-- Apply after 20261026_vault_incidents_evidence_audit.sql.
CREATE TABLE vault_sessions (
    id VARCHAR(36) PRIMARY KEY,
    required_persons INTEGER NOT NULL CHECK (required_persons IN (1,2)),
    camera_id VARCHAR(128),
    started_at TIMESTAMPTZ NOT NULL,
    authenticated_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    end_reason VARCHAR(64)
);

-- The legacy field could contain the token credential; erase it before making nullable.
UPDATE vault_room_sessions SET dual_control_session_id = NULL;
ALTER TABLE vault_room_sessions ALTER COLUMN dual_control_session_id DROP NOT NULL;
ALTER TABLE vault_room_sessions ADD COLUMN session_ref VARCHAR(36);
CREATE INDEX ix_vault_room_sessions_session_ref ON vault_room_sessions(session_ref);

ALTER TABLE vault_room_alerts
    ADD COLUMN session_ref VARCHAR(36),
    ADD COLUMN dedup_key VARCHAR(512),
    ADD COLUMN row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1),
    ADD COLUMN resolution_note TEXT,
    ADD COLUMN resolution_source VARCHAR(16) CHECK (resolution_source IS NULL OR resolution_source IN ('OPERATOR','SYSTEM')),
    ADD COLUMN evidence_status VARCHAR(16) NOT NULL DEFAULT 'NONE' CHECK (evidence_status IN ('NONE','PENDING','CAPTURED','FAILED'));
ALTER TABLE vault_incidents
    ADD COLUMN session_ref VARCHAR(36),
    ADD COLUMN legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN hold_reason TEXT,
    ADD COLUMN row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version >= 1);
ALTER TABLE vault_evidence
    ADD COLUMN session_ref VARCHAR(36),
    ADD COLUMN thumbnail_public_id VARCHAR(255);
CREATE INDEX ix_vault_room_alerts_session_ref ON vault_room_alerts(session_ref);
CREATE INDEX ix_vault_room_alerts_status_severity_created ON vault_room_alerts(status, severity, created_at DESC);
CREATE INDEX ix_vault_room_alerts_created_id_cursor ON vault_room_alerts(created_at DESC, id DESC);
CREATE INDEX ix_vault_incidents_session_ref ON vault_incidents(session_ref);
CREATE UNIQUE INDEX uq_vault_incidents_active_session ON vault_incidents(session_ref)
    WHERE session_ref IS NOT NULL AND status IN ('OPEN','INVESTIGATING');
CREATE INDEX ix_vault_evidence_session_ref ON vault_evidence(session_ref);
CREATE UNIQUE INDEX uq_vault_room_alerts_active_dedup ON vault_room_alerts(dedup_key)
    WHERE dedup_key IS NOT NULL AND status IN ('OPEN','ACKNOWLEDGED');

CREATE TABLE vault_alert_conditions (
    condition_key VARCHAR(512) PRIMARY KEY,
    session_ref VARCHAR(36),
    camera_id VARCHAR(128),
    alert_type VARCHAR(64) NOT NULL,
    discriminator VARCHAR(64) NOT NULL DEFAULT '',
    episode INTEGER NOT NULL DEFAULT 0 CHECK (episode >= 0),
    active BOOLEAN NOT NULL DEFAULT FALSE,
    clear_since TIMESTAMPTZ,
    last_touch_at TIMESTAMPTZ,
    active_alert_id VARCHAR(36),
    operator_closed_episode BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX ix_vault_alert_conditions_session_ref ON vault_alert_conditions(session_ref);
CREATE INDEX ix_vault_alert_conditions_camera_id ON vault_alert_conditions(camera_id);

CREATE SEQUENCE vault_incident_number_seq;
ALTER TABLE vault_incidents ALTER COLUMN incident_number SET DEFAULT
    ('INC-' || lpad(nextval('vault_incident_number_seq')::text, 6, '0'));

CREATE OR REPLACE FUNCTION reject_vault_audit_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'vault_audit_events is append-only';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_vault_audit_append_only
    BEFORE UPDATE OR DELETE ON vault_audit_events
    FOR EACH ROW EXECUTE FUNCTION reject_vault_audit_mutation();
-- A future retention job must use a separately controlled owner/maintenance
-- procedure that temporarily disables this trigger under audited change control.
