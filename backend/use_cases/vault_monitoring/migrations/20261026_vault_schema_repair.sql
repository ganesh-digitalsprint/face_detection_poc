-- Repair databases where the Stage 3 migration ran before its Stage 1 prerequisite.
-- Every operation is additive so this also works after either migration has run.

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
    ADD COLUMN IF NOT EXISTS metadata JSON NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS session_ref VARCHAR(36),
    ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(512),
    ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS resolution_note TEXT,
    ADD COLUMN IF NOT EXISTS resolution_source VARCHAR(16),
    ADD COLUMN IF NOT EXISTS evidence_status VARCHAR(16) NOT NULL DEFAULT 'NONE';

UPDATE vault_room_alerts SET
    first_seen_at = COALESCE(first_seen_at, opened_at),
    last_seen_at = COALESCE(last_seen_at, closed_at, opened_at),
    status = CASE WHEN closed_at IS NULL THEN 'OPEN' ELSE 'RESOLVED' END
WHERE first_seen_at IS NULL OR last_seen_at IS NULL;

ALTER TABLE vault_room_sessions
    ALTER COLUMN dual_control_session_id DROP NOT NULL;

ALTER TABLE vault_room_sessions
    ADD COLUMN IF NOT EXISTS session_ref VARCHAR(36),
    ADD COLUMN IF NOT EXISTS peak_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS seconds_at_count JSON NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS alert_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS count_at_expiry INTEGER,
    ADD COLUMN IF NOT EXISTS count_at_close INTEGER;

ALTER TABLE vault_incidents
    ADD COLUMN IF NOT EXISTS session_ref VARCHAR(36),
    ADD COLUMN IF NOT EXISTS legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS hold_reason TEXT,
    ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1;

ALTER TABLE vault_evidence
    ADD COLUMN IF NOT EXISTS session_ref VARCHAR(36),
    ADD COLUMN IF NOT EXISTS thumbnail_public_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS storage_delivery_type VARCHAR(24) NOT NULL DEFAULT 'authenticated';

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_vault_room_alerts_status') THEN
        ALTER TABLE vault_room_alerts ADD CONSTRAINT ck_vault_room_alerts_status
            CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED','DISMISSED'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_vault_room_alerts_occurrence_count') THEN
        ALTER TABLE vault_room_alerts ADD CONSTRAINT ck_vault_room_alerts_occurrence_count CHECK (occurrence_count >= 1);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_vault_room_alerts_count_at_open') THEN
        ALTER TABLE vault_room_alerts ADD CONSTRAINT ck_vault_room_alerts_count_at_open CHECK (count_at_open IS NULL OR count_at_open >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_vault_room_alerts_expected') THEN
        ALTER TABLE vault_room_alerts ADD CONSTRAINT ck_vault_room_alerts_expected CHECK (expected IS NULL OR expected >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_vault_room_alerts_observed_count') THEN
        ALTER TABLE vault_room_alerts ADD CONSTRAINT ck_vault_room_alerts_observed_count CHECK (observed_count IS NULL OR observed_count >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_vault_room_alerts_required_count') THEN
        ALTER TABLE vault_room_alerts ADD CONSTRAINT ck_vault_room_alerts_required_count CHECK (required_count IS NULL OR required_count >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_vault_room_alerts_resolution_source') THEN
        ALTER TABLE vault_room_alerts ADD CONSTRAINT ck_vault_room_alerts_resolution_source
            CHECK (resolution_source IS NULL OR resolution_source IN ('OPERATOR','SYSTEM'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_vault_room_alerts_evidence_status') THEN
        ALTER TABLE vault_room_alerts ADD CONSTRAINT ck_vault_room_alerts_evidence_status
            CHECK (evidence_status IN ('NONE','PENDING','CAPTURED','FAILED'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_vault_room_alerts_incident') THEN
        ALTER TABLE vault_room_alerts ADD CONSTRAINT fk_vault_room_alerts_incident
            FOREIGN KEY (incident_id) REFERENCES vault_incidents(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_vault_room_sessions_session_ref ON vault_room_sessions(session_ref);
CREATE INDEX IF NOT EXISTS ix_vault_room_alerts_session_ref ON vault_room_alerts(session_ref);
CREATE INDEX IF NOT EXISTS ix_vault_room_alerts_camera_id ON vault_room_alerts(camera_id);
CREATE INDEX IF NOT EXISTS ix_vault_room_alerts_incident_id ON vault_room_alerts(incident_id);
CREATE INDEX IF NOT EXISTS ix_vault_room_alerts_status_severity_created ON vault_room_alerts(status, severity, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_vault_room_alerts_created_id_cursor ON vault_room_alerts(created_at DESC, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vault_room_alerts_active_dedup ON vault_room_alerts(dedup_key)
    WHERE dedup_key IS NOT NULL AND status IN ('OPEN','ACKNOWLEDGED');
CREATE INDEX IF NOT EXISTS ix_vault_incidents_session_ref ON vault_incidents(session_ref);
CREATE INDEX IF NOT EXISTS ix_vault_evidence_session_ref ON vault_evidence(session_ref);

-- Stage 3 assigns human-readable incident numbers from this sequence.
CREATE SEQUENCE IF NOT EXISTS vault_incident_number_seq;
SELECT setval(
    'vault_incident_number_seq',
    GREATEST(COALESCE(MAX((substring(incident_number FROM '^INC-([0-9]+)$'))::BIGINT), 0), 1),
    COALESCE(MAX((substring(incident_number FROM '^INC-([0-9]+)$'))::BIGINT) > 0, FALSE)
)
FROM vault_incidents;
ALTER TABLE vault_incidents ALTER COLUMN incident_number SET DEFAULT
    ('INC-' || lpad(nextval('vault_incident_number_seq')::text, 6, '0'));
