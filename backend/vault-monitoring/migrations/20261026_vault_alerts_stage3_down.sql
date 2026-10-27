-- Down migration for 20261026_vault_alerts_stage3.sql.
DROP TRIGGER IF EXISTS trg_vault_audit_append_only ON vault_audit_events;
DROP FUNCTION IF EXISTS reject_vault_audit_mutation();
ALTER TABLE vault_incidents ALTER COLUMN incident_number DROP DEFAULT;
DROP SEQUENCE IF EXISTS vault_incident_number_seq;
DROP INDEX IF EXISTS ix_vault_alert_conditions_session_ref;
DROP INDEX IF EXISTS ix_vault_alert_conditions_camera_id;
DROP TABLE IF EXISTS vault_alert_conditions;
DROP INDEX IF EXISTS ix_vault_room_sessions_session_ref;
ALTER TABLE vault_room_sessions DROP COLUMN session_ref;
DROP INDEX IF EXISTS uq_vault_room_alerts_active_dedup;
DROP INDEX IF EXISTS ix_vault_room_alerts_session_ref;
DROP INDEX IF EXISTS ix_vault_room_alerts_status_severity_created;
DROP INDEX IF EXISTS ix_vault_room_alerts_created_id_cursor;
DROP INDEX IF EXISTS ix_vault_incidents_session_ref;
DROP INDEX IF EXISTS uq_vault_incidents_active_session;
DROP INDEX IF EXISTS ix_vault_evidence_session_ref;
ALTER TABLE vault_room_alerts DROP COLUMN session_ref, DROP COLUMN dedup_key,
    DROP COLUMN row_version, DROP COLUMN resolution_note, DROP COLUMN resolution_source,
    DROP COLUMN evidence_status;
ALTER TABLE vault_incidents DROP COLUMN session_ref, DROP COLUMN legal_hold,
    DROP COLUMN hold_reason, DROP COLUMN row_version;
ALTER TABLE vault_evidence DROP COLUMN session_ref, DROP COLUMN thumbnail_public_id;
DROP TABLE vault_sessions;
