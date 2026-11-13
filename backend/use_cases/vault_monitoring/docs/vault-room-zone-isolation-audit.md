# Vault Room zone isolation audit — 2026-11-12

## Result and scope

The Vault Room editor already had a separate file namespace and router. No storage
collision with Grill Gate was found. Several narrower snapshot, admission, working
directory and asynchronous frontend-state risks were found and fixed in place.
No tables, duplicate profile APIs, or replacement storage systems were introduced.
No saved polygons were deleted, reset, rounded, or migrated. No detector, tracker,
event rule, alert threshold, Grill Gate implementation, or editor design was changed.

Isolation is by **use case + selected profile**, with source-specific defaults.
The private profile files do not contain a physical-camera foreign key. `webcam`,
`cctv`, and `upload` are intentionally source-group defaults, not automatically
discovered physical camera identities. Distinct viewpoints require distinct named
profiles. This audit verifies source/profile isolation; it does not claim automatic
physical-camera identification or hardware switching across multiple cameras of the
same source type. The separate registry assignment path supplies physical-camera
identity when that integration is configured.

## 1. Exact storage and configuration flow

| Configuration path | Storage | Scope/fields |
| --- | --- | --- |
| Vault Room Zones & Regions editor | `D:/fedbank/backend/use_cases/vault_monitoring/var/vault-room-region-profiles/{profile_id}.json` | Filename is the profile ID. JSON has `name`, `version`, `zones`, and a `confirmation_seconds` map keyed by zone ID. |
| Legacy Vault registry/file adapter | `backend/use_cases/vault_monitoring/config/vault_zones.json` by default; `VAULT_ZONES_FILE` OS environment override | Only the configured active Vault assignment may manage this file. This default file is absent in this checkout; it is not the five-region editor's storage. |
| Registry database mode | `registry_zones` joined/scoped through `camera_use_case_assignments`, `registry_cameras`, `registry_locations` | `registry_zones.assignment_id`, `zone_key`, `polygon`, `reference`, `properties`, `enabled`, `version`, `coordinate_system`; assignment carries `camera_id`, `use_case`, `configuration.source_id`, `zones_version`. |
| Grill Gate reusable configurations | PostgreSQL `grill_gate_zone_configurations` | `owner_id`, `id`, `name`, frame dimensions, `config_json.zones`; owner-scoped routes. |
| Grill Gate uploaded runs | PostgreSQL `grill_gate_video_jobs` | `id`, `config_snapshot.zones`, source/job metadata; job configuration locks when processing starts. |

The five private Vault keys are `person_monitoring_roi`, `vault_area_roi`,
`vault_door_roi`, `tray_area_roi`, and `ornament_area_roi`. The private save schema
and service allow only these IDs. Generic registry zone type manifests are separate:
`config/use_cases/registry.yaml` and `{vault-room,grill-gate,branch-exterior}/zone_types.yaml`.
The Vault manifest currently has an empty `zone_types` list; the five private editor
keys come from the private profile service/schema, not this legacy manifest.

The legacy provider is controlled by `vault_room.zones_source` (`file`/`database`)
and `vault_room.active_assignment` in `config/models.yaml`. It selects only active
`use_case == "vault_room"` assignments/cameras/locations. Database zones must use
`normalized_raw`; the active assignment is resolved before loading its rows.

Flow for the five-region editor:

1. `frontend/.../hooks/useVaultRoomRegions.js` owns the selected source/profile and drafts.
2. `frontend/.../api/vaultRoom.js` calls the private Vault router.
3. `app/api/routes/vault_region_profiles.py` validates the payload and delegates to
   `app/services/vault_region_profiles.py`.
4. `VaultRegionProfiles.save` validates through existing `zone_from_dict`, writes
   only the selected profile via staged atomic replacement, and checks its version.
5. A camera activation or replay start loads a profile; `VaultRegionMonitor` owns
   a deep snapshot for that processing context. Saving a file never edits that snapshot.

`get_vault_region_profiles` caches one **service object**, not polygon payloads;
each `load` reads JSON and builds new values. The service's RLock/version check is
process-local: the current launcher uses one Vault worker. This is not a distributed
multi-writer transaction scheme. Static registry/model metadata caches are separate
from per-session ROI state.

## 2. Profile identification and API boundaries

Default IDs: `webcam`, `cctv`, `upload`. New named profiles receive UUID hex IDs.
Names are display labels, never storage paths. IDs must match `[a-z0-9_-]{1,64}`;
clients cannot submit a filesystem root, table name, or use-case override.

All private endpoints require the existing Vault Room API-key dependency:

| Method | Path under `/api/v1/vault-room/region-profiles` | Operation |
| --- | --- | --- |
| GET | base | List Vault profiles only |
| POST | base | Create a named Vault profile |
| GET | `/{profile_id}` | Load that profile |
| PUT | `/{profile_id}` | Replace that profile's zone list with optimistic version checking |
| POST | `/{profile_id}/activate` | Admit a snapshot for the live room |

Deleting a region is a scoped PUT of the selected profile's remaining polygons.
There is no private profile-delete endpoint. A Grill Gate configuration UUID sent
to this API cannot retrieve its DB record; it addresses only the Vault directory.

The common registry `/api/v1/regions/assignments/{assignment_id}/zones` routes use
GET/POST, with PATCH/DELETE on an individual zone and POST for enabled state.
Backend mutations include the assignment predicate; a zone UUID/key alone cannot
mutate a row from another assignment. The file-backed Vault adapter additionally
checks `assignment.use_case == "vault_room"` and the configured active assignment.
Grill Gate uses `/api/v1/grill-gate/zone-configurations` and
`/api/v1/grill-gate/videos/{job_id}/config`. Its named configurations are owner scoped.
The common operator credential is not a per-camera/tenant authorization model;
the isolation described here concerns configuration namespaces and processing state.

## 3. Frontend and preview isolation

Vault selection keys are `vault-room-region-profile:{webcam|cctv|upload}`. They do
not contain polygons. Grill Gate uses `grill-gate-video-zones:{file...}:{frame...}`
and `grill-gate:video-zone-configuration:{asset_id}`. No keys are shared.

The shared `PolygonFrameCanvas.jsx` receives zones as props and has instance-local
SVG/drag refs. It owns no module-global zone state. Grill Gate's SourceEditor is
mounted per source; Vault's hook owns its separate state. The shared component and
Grill Gate source editor were not modified.

The existing `active && target && frame` portal guard in `VaultRoomZones.jsx`
continues rendering polygons only in Zones & Regions. Camera playback/processed
frames remain clean; backend ROI evaluation remains active. Backend annotation
draws person boxes/optional poses rather than ROI polygons.

## 4. Conflicts found and fixes

| File changed | Finding and targeted correction |
| --- | --- |
| `app/services/vault_region_profiles.py` | A relative default root could silently select a different profile directory when launched from another cwd. Anchor the existing default to the Vault service directory. Explicit test/deployment roots remain supported. The repo-root alternative directory was checked and does not exist, so no competing saved data was moved or hidden. |
| `app/services/vault_region_monitor.py` | The monitor retained the caller's nested profile dictionary. Deep-copy it before deriving the monitor's zone map. |
| `app/services/vault_room_replay.py` | A mutable profile was passed directly to a worker thread. Snapshot it at start admission, before thread handoff. |
| `app/services/vault_room_manager.py` | New replays inherited the live camera's generic registry/file zone monitor. Stop inheriting those zones; the replay receives only its explicit profile, or no ROI when no profile is supplied. Also reject live activation during an access/vault session or an in-flight frame; replay configuration remains local and does not contend with the shared model during snapshot preparation. |
| `app/api/routes/vault_region_profiles.py` | Translate manager admission failures to the existing 409 contract rather than a server error. Saving next-session changes remains allowed; activating another profile requires finishing the current session. |
| `frontend/.../hooks/useVaultRoomRegions.js` | Late create/save/pause/activate responses could update a new tab/source context. Add context-generation checks and a render-time loaded-profile guard. Old polygons do not flash during selection changes; stale responses cannot select a profile under the wrong source. |
| `tests/test_vault_region_isolation.py` | Add six isolation tests, reusing the existing real Grill Gate router/SQLite harness. |
| This report | Record boundaries, findings, changes, test results and limits. |

The live Vault pipeline still admits one backend camera; the replay manager still
admits one actively processing replay. Live/replay managers may share only the
existing detector and inference semaphore, not region monitors or event state.
No source admission, alert/event algorithm, or detector/tracker algorithm was redesigned.

## 5. Regression results

**Passed:** all six new isolation cases and all Vault-focused tests in the broader
run. Combined run: **159 passed, 5 failed** across Vault and the Grill Gate video API
suite. The failures are in the unchanged Grill Gate test/module behavior:

- `test_named_zone_configuration_create_list_get_update_duplicate_delete`
- `test_config_locks_at_start_so_the_running_snapshot_cannot_change`
- `test_job_is_not_completed_until_its_events_are_stored`
- `test_live_and_video_processors_share_no_state_and_tag_events_by_source`
- `test_source_change_keeps_grill_gate_alert_rules`

These concern corridor/config normalization, job result expectations, and expanded
alert configuration defaults. They are recorded as failures, not passes, and were
not changed to make this audit green. Isolated diagnostic reruns reproduced five
failure markers but stalled during test finalization and were terminated; they are
not counted as additional completed runs.

Verified scenarios:

- Save/reload/delete Vault profiles in temporary JSON storage; source defaults and
  a separate named camera profile remain independent after deletion/reconstruction.
- Save Vault while a real Grill Gate named configuration exists in a temporary DB;
  edit Grill Gate through its real API and confirm Vault is unchanged. Identical
  zone key strings across the use cases remain independent.
- Reject foreign profile IDs, path traversal and foreign region types in the Vault API.
- Changing stored/caller-owned polygons cannot modify active monitors; concurrently
  evaluated Vault A, Vault B and Grill Gate geometry remain independent.
- Replay creation does not inherit live legacy zones; thread admission snapshots the
  selected profile before subsequent caller mutations. Active/in-flight profile
  activation is rejected, and the existing snapshot is retained.
- Browser checks with mocked profile APIs: source/refresh switching, no old polygon
  flash, late create/save responses after leaving the editor, and camera-tab overlay
  removal/restoration on returning to the editor all passed.
- Frontend production build passed.
- The actual existing `upload.json` remains present with all five regions; its SHA-256
  stayed `71079DAA7B2BCADCC1756A793974D3DA82776327C5ED0E46ACF21D2B4D9CD4DF`
  across the regression run. Production configurations were not used as writable fixtures.

**Unverified:** simultaneous physical Webcam/CCTV + Grill Gate RF-DETR runs; automatic
selection between multiple physical cameras of the same source type; browser tests
against live Grill Gate production configurations (the API isolation test uses a
temporary database); cross-process/multiple-Uvicorn-worker file-write contention.
These must not be inferred from isolated engine/fixture tests.

Backend changes require a Vault service restart to replace existing in-memory managers.
