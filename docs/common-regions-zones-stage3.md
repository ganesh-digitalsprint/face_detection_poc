# Common Regions & Zones Stage 3

## What is implemented

Vault Monitoring owns the common registry tables and `/api/v1/regions` API. Branch Exterior remains on its current camera and zone tables, IDs, API contracts, and cropped-analysis-frame coordinates. There is no automatic Branch registration or migration. Grill Gate can use common assignments and database zones, but no detection, streaming, monitoring, or alerts were added.

The common schema is `Location -> Camera -> Source` and `Camera -> UseCaseAssignment -> Zones`. Zone rows carry an explicit coordinate system, enabled flag, per-row version, and assignment-level `zones_version`. Use-case and zone-type labels come from `config/use_cases/` YAML. Unknown existing zone types remain readable and are marked `type_unknown`.

Vault JSON remains the default (`zones_source: file`). The `config/vault_zones.json` file is not created during startup or read-only listing; it is created by the first successful save. Writes validate the full replacement and restore the previous file if the database version/audit commit fails. Vault loads enabled JSON zones once at the start of an access attempt, holds that frozen zone set for the session, and picks up later edits on the next attempt. `process_frame` does not call the provider or access file/database storage. Database mode is available by setting `zones_source: database` and selecting an `active_assignment`; Vault DB zones must use `normalized_raw` coordinates.

## Migration

SQL migrations in this service are applied manually. Back up the PostgreSQL database, review the migration against the live schema, then apply:

```powershell
psql $env:VAULT_DATABASE_URL -v ON_ERROR_STOP=1 -f backend/use_cases/vault_monitoring/migrations/20261103_common_camera_registry.sql
```

If the application uses a SQLAlchemy-style URL such as `postgresql+psycopg://...`, use the equivalent PostgreSQL connection accepted by `psql`; do not print or commit credentials. Restart Vault Monitoring after the migration so SQLAlchemy model metadata and the router are loaded. The down migration is `20261103_common_camera_registry_down.sql`; take a fresh backup before using it because it removes registry data and Vault session identity columns.

No migration has been applied to a live PostgreSQL database as part of this implementation. `create_all` at startup is not a replacement for this schema migration.

## API

All endpoints require the existing `X-API-Key` operator key. The browser client reads `VITE_VAULT_ROOM_API_KEY`; the server still validates it through the existing Vault dependency.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/regions/use-cases` | Configured use cases and zone types |
| GET/POST | `/api/v1/regions/locations` | List (optional `use_case`) or create locations |
| PATCH/DELETE | `/api/v1/regions/locations/{location_id}` | Update or deactivate |
| GET/POST | `/api/v1/regions/cameras` | List (optional `location_id`, `use_case`) or create logical cameras |
| PATCH/DELETE | `/api/v1/regions/cameras/{camera_id}` | Update or deactivate |
| GET | `/api/v1/regions/cameras/{camera_id}/sources` | List masked source details |
| POST | `/api/v1/regions/sources` | Create a source from a server-side reference |
| PATCH/DELETE | `/api/v1/regions/sources/{source_id}` | Update or deactivate a source |
| GET/POST | `/api/v1/regions/assignments` | List (optional filters) or create assignments |
| PATCH/DELETE | `/api/v1/regions/assignments/{assignment_id}` | Update or deactivate |
| GET/POST | `/api/v1/regions/assignments/{assignment_id}/zones` | List (optional `enabled`) or create zones |
| PATCH/DELETE | `/api/v1/regions/assignments/{assignment_id}/zones/{zone_id}` | Update or delete a zone |
| POST | `/api/v1/regions/assignments/{assignment_id}/zones/{zone_id}/enabled?enabled=true` | Enable or disable |

Use `env:CAMERA_SOURCE_NAME` as `connection_ref` for RTSP/HTTP/video file sources. Put the actual URL/path in the server environment, never in the request or database. Browser webcams use a non-secret reference such as `browser:terminal-01:camera-01`; server webcams use `device:0`. Source responses include only masked display text and a credential-free fingerprint. Create a source before creating an assignment, and set the source ID in assignment `configuration.source_id`.

Example request bodies (replace IDs and secrets with locally configured values):

```json
{"code":"vault-room-1","name":"Vault Room 1"}
```

```json
{"location_id":"<location-uuid>","code":"camera-01","name":"Camera 01"}
```

```json
{"camera_id":"<camera-uuid>","source_type":"rtsp","connection_ref":"env:VAULT_CAMERA_01_RTSP"}
```

```json
{"camera_id":"<camera-uuid>","use_case":"vault_room","configuration":{"source_id":"<source-uuid>"}}
```

```json
{"zone_key":"safe-area","name":"Safe area","reference":"bottom_center","polygon":[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]]}
```

Locations, cameras, sources, assignments, and PostgreSQL zones survive application restarts. Vault JSON zones survive browser refresh and process restart when the configured server filesystem persists. They are lost if that filesystem or volume is replaced without backup. No common records or sample zones are seeded.

## Frontend status and limits

`/regions` now opens the common Regions & Zones UI for Vault Room and Grill Gate. It loads configured use cases and zone types, lists locations and assigned cameras, creates locations and camera/source/assignment records, loads zones after selection or page refresh, and supports polygon draw/edit, enable/disable and delete. Vault uses the JSON zone fields and raw unmirrored normalized coordinates. Grill zones use assignment scoped PostgreSQL storage and configured types. RTSP URLs remain server-side environment variables; the UI accepts only an `env:NAME` reference. Browser webcam sources use the browser camera preview, can capture a still frame, and can resume the live preview; image uploads also work as drawing frames.

Branch Exterior selection opens the existing page within its Branch layout. Its adapter continues sending legacy camera IDs to its existing APIs and preserves `restricted`, `alert_mode`, `alert_severity` and `zone_type` meanings. No automatic Branch registration or assignment is created.

The common page does not yet preview server-side RTSP, HTTP, file, or server webcam sources; those sources can use an uploaded frame. No Grill detection, stream reader, or alert behavior was added.

## Verification

- Vault registry, zone persistence, model, and session snapshot focused tests: **8 passed**.
- Relevant Vault regression subset: **45 passed, 1 failed**. The failure is `test_unavailable_webcam_reports_failure_and_releases_capture`: current webcam reconnect behavior takes longer than the test's 2-second wait. It reproduces by itself and is in the pre-existing camera-stream worktree changes, outside this Regions & Zones change. Excluding that failing camera test, the focused new registry/session and relevant Vault regressions pass: **36 passed**.
- Frontend tests: **46 passed**.
- Frontend production build succeeded when directed to a temporary output directory. The normal `dist` output was locked by a running process; the temporary build emitted only the existing large-bundle warning.
- PostgreSQL migration/runtime behavior was not verified against a live database.
