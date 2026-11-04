-- Rollback for 20261103_common_camera_registry.sql. Registry tables must be empty or have their data backed up first.
BEGIN;
ALTER TABLE vault_room_sessions DROP COLUMN IF EXISTS assignment_id;
ALTER TABLE vault_room_sessions DROP COLUMN IF EXISTS camera_id;
ALTER TABLE vault_room_sessions DROP COLUMN IF EXISTS location_id;
DROP TABLE IF EXISTS registry_zones;
DROP TABLE IF EXISTS camera_use_case_assignments;
DROP TABLE IF EXISTS camera_sources;
DROP TABLE IF EXISTS registry_cameras;
DROP TABLE IF EXISTS registry_locations;
COMMIT;
