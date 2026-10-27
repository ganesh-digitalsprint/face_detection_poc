-- Stage 1 incident workflow. Apply after existing vault-room migrations.
-- Existing vault_room_alerts remain the canonical alert table.
ALTER TABLE vault_room_alerts
    ADD COLUMN IF NOT EXISTS title VARCHAR(200),
    ADD COLUMN IF NOT EXISTS source VARCHAR(40) NOT NULL DEFAULT 'VAULT_MONITORING',
    ADD COLUMN IF NOT EXISTS observed_count INTEGER,
    ADD COLUMN IF NOT EXISTS required_count INTEGER,
    ADD COLUMN IF NOT EXISTS camera_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS occurrence_count INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'OPEN',
    ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS acknowledged_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS resolved_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS dismissed_by VARCHAR(128),
    ADD COLUMN IF NOT EXISTS incident_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS metadata JSON NOT NULL DEFAULT '{}';

UPDATE vault_room_alerts SET
    first_seen_at = COALESCE(first_seen_at, opened_at),
    last_seen_at = COALESCE(last_seen_at, closed_at, opened_at),
    status = CASE WHEN closed_at IS NULL THEN 'OPEN' ELSE 'RESOLVED' END
WHERE first_seen_at IS NULL OR last_seen_at IS NULL;

ALTER TABLE vault_room_alerts
    ADD CONSTRAINT ck_vault_room_alerts_status CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED','DISMISSED')),
    ADD CONSTRAINT ck_vault_room_alerts_occurrence_count CHECK (occurrence_count >= 1),
    ADD CONSTRAINT ck_vault_room_alerts_count_at_open CHECK (count_at_open IS NULL OR count_at_open >= 0),
    ADD CONSTRAINT ck_vault_room_alerts_expected CHECK (expected IS NULL OR expected >= 0),
    ADD CONSTRAINT ck_vault_room_alerts_observed_count CHECK (observed_count IS NULL OR observed_count >= 0),
    ADD CONSTRAINT ck_vault_room_alerts_required_count CHECK (required_count IS NULL OR required_count >= 0);

CREATE INDEX ix_vault_room_alerts_status_created ON vault_room_alerts(status, created_at DESC);
CREATE INDEX ix_vault_room_alerts_severity ON vault_room_alerts(severity);
CREATE INDEX ix_vault_room_alerts_type ON vault_room_alerts(type);
CREATE INDEX ix_vault_room_alerts_camera_id ON vault_room_alerts(camera_id);
CREATE INDEX ix_vault_room_alerts_incident_id ON vault_room_alerts(incident_id);

CREATE TABLE vault_incidents (
    id VARCHAR(36) PRIMARY KEY,
    incident_number VARCHAR(40) NOT NULL UNIQUE,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','INVESTIGATING','RESOLVED','CLOSED')),
    severity VARCHAR(16) NOT NULL DEFAULT 'WARNING' CHECK (severity IN ('INFO','WARNING','HIGH','CRITICAL')),
    session_id VARCHAR(36),
    camera_id VARCHAR(128),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    created_by VARCHAR(128),
    retention_hold BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSON NOT NULL DEFAULT '{}'
);
ALTER TABLE vault_room_alerts ADD CONSTRAINT fk_vault_room_alerts_incident
    FOREIGN KEY (incident_id) REFERENCES vault_incidents(id) ON DELETE SET NULL;
CREATE INDEX ix_vault_incidents_status_updated ON vault_incidents(status, updated_at DESC);
CREATE INDEX ix_vault_incidents_session_id ON vault_incidents(session_id);
CREATE INDEX ix_vault_incidents_camera_id ON vault_incidents(camera_id);

CREATE TABLE vault_evidence (
    id VARCHAR(36) PRIMARY KEY,
    incident_id VARCHAR(36) REFERENCES vault_incidents(id) ON DELETE RESTRICT,
    alert_id VARCHAR(36) REFERENCES vault_room_alerts(id) ON DELETE RESTRICT,
    evidence_type VARCHAR(32) NOT NULL,
    storage_provider VARCHAR(32) NOT NULL DEFAULT 'CLOUDINARY',
    storage_public_id VARCHAR(255),
    resource_type VARCHAR(32),
    asset_format VARCHAR(16),
    mime_type VARCHAR(100),
    width INTEGER CHECK (width IS NULL OR width > 0),
    height INTEGER CHECK (height IS NULL OR height > 0),
    file_size_bytes INTEGER CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),
    captured_at TIMESTAMPTZ,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    uploaded_by VARCHAR(128),
    camera_id VARCHAR(128),
    session_id VARCHAR(36),
    comment TEXT,
    checksum VARCHAR(128),
    available BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSON NOT NULL DEFAULT '{}',
    CONSTRAINT ck_vault_evidence_parent CHECK (alert_id IS NOT NULL OR incident_id IS NOT NULL)
);
CREATE INDEX ix_vault_evidence_incident ON vault_evidence(incident_id);
CREATE INDEX ix_vault_evidence_alert ON vault_evidence(alert_id);
CREATE INDEX ix_vault_evidence_session_id ON vault_evidence(session_id);

CREATE TABLE vault_incident_comments (
    id VARCHAR(36) PRIMARY KEY,
    incident_id VARCHAR(36) NOT NULL REFERENCES vault_incidents(id) ON DELETE RESTRICT,
    evidence_id VARCHAR(36) REFERENCES vault_evidence(id) ON DELETE RESTRICT,
    author_id VARCHAR(128) NOT NULL,
    body TEXT NOT NULL CHECK (length(trim(body)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX ix_vault_incident_comments_incident_created ON vault_incident_comments(incident_id, created_at);

CREATE TABLE vault_audit_events (
    id VARCHAR(36) PRIMARY KEY,
    actor_id VARCHAR(128),
    action VARCHAR(64) NOT NULL,
    entity_type VARCHAR(32) NOT NULL,
    entity_id VARCHAR(36) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    details JSON NOT NULL DEFAULT '{}'
);
CREATE INDEX ix_vault_audit_entity ON vault_audit_events(entity_type, entity_id, created_at);

-- Down migration (manual): drop vault_audit_events, vault_incident_comments,
-- vault_evidence, FK/indexes on vault_room_alerts, vault_incidents, then the
-- added alert columns and constraints. This preserves all original alert rows.
