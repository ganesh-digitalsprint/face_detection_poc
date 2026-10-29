-- Rollback for 20261026_vault_incidents_evidence_audit.sql.
-- This removes Stage 1 workflow data; export it first if it must be retained.
DROP TABLE vault_audit_events;
DROP TABLE vault_incident_comments;
DROP TABLE vault_evidence;
ALTER TABLE vault_room_alerts DROP CONSTRAINT fk_vault_room_alerts_incident;
DROP TABLE vault_incidents;
DROP INDEX ix_vault_room_alerts_status_created;
DROP INDEX ix_vault_room_alerts_severity;
DROP INDEX ix_vault_room_alerts_type;
DROP INDEX ix_vault_room_alerts_camera_id;
DROP INDEX ix_vault_room_alerts_incident_id;
ALTER TABLE vault_room_alerts
    DROP CONSTRAINT ck_vault_room_alerts_status,
    DROP CONSTRAINT ck_vault_room_alerts_occurrence_count,
    DROP CONSTRAINT ck_vault_room_alerts_count_at_open,
    DROP CONSTRAINT ck_vault_room_alerts_expected,
    DROP CONSTRAINT ck_vault_room_alerts_observed_count,
    DROP CONSTRAINT ck_vault_room_alerts_required_count,
    DROP COLUMN title,
    DROP COLUMN source,
    DROP COLUMN observed_count,
    DROP COLUMN required_count,
    DROP COLUMN camera_id,
    DROP COLUMN first_seen_at,
    DROP COLUMN last_seen_at,
    DROP COLUMN occurrence_count,
    DROP COLUMN created_at,
    DROP COLUMN updated_at,
    DROP COLUMN status,
    DROP COLUMN acknowledged_at,
    DROP COLUMN acknowledged_by,
    DROP COLUMN resolved_at,
    DROP COLUMN resolved_by,
    DROP COLUMN dismissed_at,
    DROP COLUMN dismissed_by,
    DROP COLUMN incident_id,
    DROP COLUMN metadata;
