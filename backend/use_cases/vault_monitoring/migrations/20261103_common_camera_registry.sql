-- Common, Vault-owned registry foundation. Branch Exterior legacy tables and data are untouched.
BEGIN;

CREATE TABLE IF NOT EXISTS registry_locations (
    id UUID PRIMARY KEY,
    code VARCHAR(39) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS registry_cameras (
    id UUID PRIMARY KEY,
    location_id UUID NOT NULL REFERENCES registry_locations(id),
    code VARCHAR(39) NOT NULL,
    name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_registry_cameras_location_code UNIQUE (location_id, code)
);
CREATE INDEX IF NOT EXISTS ix_registry_cameras_location_id ON registry_cameras(location_id);

CREATE TABLE IF NOT EXISTS camera_sources (
    id UUID PRIMARY KEY,
    camera_id UUID NOT NULL REFERENCES registry_cameras(id),
    source_type VARCHAR(32) NOT NULL,
    connection_ref VARCHAR(255) NOT NULL,
    fingerprint VARCHAR(1024) NOT NULL,
    purpose VARCHAR(16) NOT NULL DEFAULT 'both',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_camera_sources_purpose CHECK (purpose IN ('detection','evidence','both'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_camera_sources_active_fingerprint
    ON camera_sources(fingerprint) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS ix_camera_sources_camera_active ON camera_sources(camera_id, is_active);

CREATE TABLE IF NOT EXISTS camera_use_case_assignments (
    id UUID PRIMARY KEY,
    camera_id UUID NOT NULL REFERENCES registry_cameras(id),
    use_case VARCHAR(39) NOT NULL,
    exclusive BOOLEAN NOT NULL DEFAULT TRUE,
    configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    calibration JSONB NULL,
    zones_version INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_camera_use_case_assignment UNIQUE (camera_id, use_case),
    CONSTRAINT ck_camera_use_case_zones_version CHECK (zones_version >= 0)
);
CREATE INDEX IF NOT EXISTS ix_camera_use_case_assignments_camera_id ON camera_use_case_assignments(camera_id);
CREATE INDEX IF NOT EXISTS ix_camera_use_case_assignments_use_case_active ON camera_use_case_assignments(use_case, is_active);

CREATE TABLE IF NOT EXISTS registry_zones (
    id UUID PRIMARY KEY,
    assignment_id UUID NOT NULL REFERENCES camera_use_case_assignments(id),
    zone_key VARCHAR(40) NOT NULL,
    name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    zone_type VARCHAR(40) NULL,
    polygon JSONB NOT NULL,
    reference VARCHAR(32) NULL,
    properties JSONB NULL,
    coordinate_system VARCHAR(40) NOT NULL,
    calibration JSONB NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    version INTEGER NOT NULL DEFAULT 1,
    imported_batch_id UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_registry_zones_assignment_key UNIQUE (assignment_id, zone_key),
    CONSTRAINT ck_registry_zones_version CHECK (version >= 1),
    CONSTRAINT ck_registry_zones_coordinate_system CHECK (coordinate_system IN ('normalized_raw','normalized_cropped_analysis')),
    CONSTRAINT ck_registry_zones_properties_size CHECK (properties IS NULL OR octet_length(properties::text) <= 4096)
);
CREATE INDEX IF NOT EXISTS ix_registry_zones_assignment_enabled ON registry_zones(assignment_id, enabled);
CREATE INDEX IF NOT EXISTS ix_registry_zones_imported_batch_id ON registry_zones(imported_batch_id);

ALTER TABLE vault_room_sessions
    ADD COLUMN IF NOT EXISTS location_id UUID NULL REFERENCES registry_locations(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS camera_id UUID NULL REFERENCES registry_cameras(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS assignment_id UUID NULL REFERENCES camera_use_case_assignments(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_vault_room_sessions_location_id ON vault_room_sessions(location_id);
CREATE INDEX IF NOT EXISTS ix_vault_room_sessions_camera_id ON vault_room_sessions(camera_id);
CREATE INDEX IF NOT EXISTS ix_vault_room_sessions_assignment_id ON vault_room_sessions(assignment_id);

COMMIT;
