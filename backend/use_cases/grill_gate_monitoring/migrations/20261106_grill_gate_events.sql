CREATE TABLE IF NOT EXISTS grill_gate_events (
    id UUID PRIMARY KEY,
    camera_id UUID NOT NULL,
    assignment_id UUID NOT NULL,
    event_type VARCHAR(40) NOT NULL CHECK (event_type IN (
        'CROSSING_COMPLETED', 'MESH_PERSON_ENTERED', 'MESH_PERSON_EXITED'
    )),
    track_id INTEGER,
    direction VARCHAR(32),
    source_zone VARCHAR(40),
    destination_zone VARCHAR(40),
    occurred_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_grill_gate_events_assignment_time
    ON grill_gate_events (assignment_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_grill_gate_events_camera_time
    ON grill_gate_events (camera_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_grill_gate_events_assignment_type_time
    ON grill_gate_events (assignment_id, event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_grill_gate_events_type_time
    ON grill_gate_events (event_type, occurred_at DESC);
