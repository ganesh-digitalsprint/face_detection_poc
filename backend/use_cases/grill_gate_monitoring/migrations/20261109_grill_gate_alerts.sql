CREATE TABLE grill_gate_alerts (
    id UUID PRIMARY KEY,
    source_event_id VARCHAR(200) NOT NULL UNIQUE,
    source_event_version INTEGER NOT NULL DEFAULT 1,
    use_case VARCHAR(39) NOT NULL DEFAULT 'grill_gate',
    source_event_type VARCHAR(100) NOT NULL,
    category VARCHAR(64),
    camera_id UUID,
    camera_name VARCHAR(120),
    assignment_id UUID,
    video_job_id UUID,
    severity VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'OPEN',
    title VARCHAR(200) NOT NULL,
    summary TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    triggered_at TIMESTAMPTZ NOT NULL,
    condition_since TIMESTAMPTZ,
    gate_open_duration_seconds DOUBLE PRECISION,
    configured_threshold_seconds DOUBLE PRECISION,
    deduplication_key VARCHAR(512),
    source_status VARCHAR(64),
    resource_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    domain_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    resolution_note VARCHAR(500),
    resolved_at TIMESTAMPTZ,
    row_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_grill_gate_alerts_use_case CHECK (use_case = 'grill_gate'),
    CONSTRAINT ck_grill_gate_alerts_status CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED'))
);

CREATE INDEX ix_grill_gate_alerts_assignment_status_time
    ON grill_gate_alerts (assignment_id, status, triggered_at);
CREATE INDEX ix_grill_gate_alerts_camera_time
    ON grill_gate_alerts (camera_id, triggered_at);
CREATE INDEX ix_grill_gate_alerts_type_time
    ON grill_gate_alerts (source_event_type, triggered_at);
