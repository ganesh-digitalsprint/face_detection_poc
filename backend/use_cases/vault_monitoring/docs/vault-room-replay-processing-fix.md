# Vault Room replay processing investigation and verification

The authorization workflow described below records the earlier investigation.
The subsequent [automatic replay authorization fix](vault-room-auto-authorization.md)
supersedes its opt-in checkbox behavior. Uploaded replay now automatically simulates
authorization after two-person confirmation; live authorization is unchanged.

## Confirmed causes

The reported completed replay was `38d21a46d9c04ab7bd8f02624dde4317`, using
`vault_authorized_employee_operation_30s_smooth.mp4` (1280×720, 24 FPS, 720 frames,
30 seconds). Its final response was inspected rather than treating the initial
`uploaded`, empty-state response as processing output.

1. **Zero scoped count:** the saved Person Monitoring Area used `bottom_center`.
   Actual RF-DETR inference at video time 1.0 returned two people with bottom-center
   points approximately `(0.4904, 0.9924)` and `(0.2467, 0.9072)`. Both are outside
   the saved polygon. The same zero-ROI membership occurred at sampled times
   0, 2, 5, 10, 15, 20 and 25 seconds. Bounding boxes were drawn from confirmed
   ByteTrack output; they were not proof of ROI membership. No detection/tracker
   thresholds or algorithms were changed.
2. **No activity events:** person events used that same excluded membership set.
   A separate integration gap also existed: count already fell back to all tracks
   without a person ROI, but activity confirmation returned an empty membership
   set, and a replay without any profile skipped the activity engine entirely.
3. **Entry warning:** the actual alert was replay-only `NO_ENTRY` at **10 seconds
   of source time**, matching `counting.mismatch_alert_after_seconds: 10` in the
   current config. It was not a 60-second production warning. Slow CPU inference
   made that point arrive much later in wall time. The source clock was already
   used correctly; the zero ROI count supplied to the alert matrix was the issue.
4. **Frontend updates:** the replay polling effect was keyed only by session ID.
   An uploaded-session poll could leave a 30-second timer after Start, and an
   in-flight status read could overwrite a newer control response. A preview-image
   fetch failure also prevented an otherwise valid count/status response from
   being applied.

The recording's last frame is genuinely empty. Occupancy remains a stabilized
signal, not a raw-frame count; late empty images do not retroactively invalidate
the earlier confirmed events.

## Targeted changes

- Preserved every polygon coordinate and changed only the existing upload profile's
  Person Monitoring Area reference to `center` (profile version 1 → 2), matching
  this upper-body view. The other four references/configurations were retained.
  The editor now exposes the existing center/bottom-center reference setting and
  preserves it when a region is redrawn. New profiles are not globally forced to center.
- Count and presence events share `monitoring_tracks`, including the intended
  full-frame fallback. A profile-less replay configures a local empty profile;
  this creates no new stored configuration.
- Replay state exposes raw detections, confirmed tracks, ROI count, stabilized
  count, IDs, membership, reference mode, source time, event invocation/types and
  alert input. Sampled/event-triggered logs include replay ID and frame number.
- Both engines consume the same stabilized count. Replay `NO_ENTRY` does not claim
  nobody entered after confirmed presence has already occurred. Live alert rules
  and configured thresholds are unchanged.
- Replay authorization remains opt-in. The camera controls provide a checkbox
  for simulated two-officer authorization, disabled unless two persons are expected.
  The choice resets on a new file. Only an isolated replay accepts it. When enabled,
  replay activity and alert state consistently see two simulated verified officers;
  the six-minute source-time session starts after two-person confirmation. Without
  it, no `SESSION_STARTED` activity is generated.
- Replay operational writes publish into the replay manager rather than the live
  room ring. The final status snapshot is refreshed after the writer drains, so
  committed activity/evidence is not missed at EOF. Public replay state/events use
  the video-session ID; the internal room ID remains available as `room_session_id`.
- Frontend polling changes cadence on processing/finalization transitions, ignores
  stale mutation-era replies, and applies state before requesting the image.
  Failed/204 preview reads retry without freezing counts. The UI explains tracked
  versus ROI counts when they differ and labels unenabled replay authorization.

## Real-recording validation

Both supplied paths were checked and have SHA-256:
`96162FC1AC51BD11C1DC66649058EC6D89B13B2492E6815CFF07E5445BEC624B`.

- `backend/use_cases/vault_monitoring/temp/vault_authorized_employee_operation_30s_smooth.mp4`
- `D:/fedbank-assets/videos/vault_authorized_employee_operation_30s_smooth.mp4`

The updated real decoder → RF-DETR → ByteTrack → ROI → stable counter → event/alert
pipeline ran against the entire recording through the existing APIs on an isolated
validation listener. It used the actual saved profile, PostgreSQL activity storage,
and durable evidence spool, not a detector fixture or hardcoded event timestamps.

| Result | No simulated authorization | Explicit simulated authorization |
| --- | --- | --- |
| Replay ID | `44af9567b7b448eab8042d7fd33b3ae6` | `220ad9eda1f44ce099cd3f62afa484ad` |
| Completion | completed, no error | completed, no error |
| Processed frames | 144 at the existing ~5 FPS sampling | 144 |
| Peak/final stabilized count | 2 / 2 | 2 / 2 |
| PERSON_DETECTED | 3 confirmed tracking episodes | 3 confirmed tracking episodes |
| PERSON_ENTERED | 1 | 1 |
| SESSION_STARTED | 0 | 1 |
| VAULT_AREA_ENTERED | 0 | 0 |
| Replay alerts | UNAUTHORIZED_ENTRY, as expected without authorization | none |
| NO_ENTRY | none | none |
| Evidence successfully retrieved | all 4 activity records | all 5 activity records |
| Wall time | about 131 seconds | about 113 seconds |
| Last processed source time | 29.7917 seconds | 29.7917 seconds |

Track 3 was confirmed later in the clip, producing another presence episode; this
is not an invented third physical identity or a second two-person entry event.
No Vault Area event was forced: the configured Vault Area reference/membership
condition did not confirm an entry in this recording. Its polygon/reference was
not relaxed to make an expected event appear.

The browser consumed the real validated replay's status, activity and evidence
responses, displaying **2 of 2**, **Events (5)**, and full-resolution event evidence.
Its launch requests were bound by the test harness to that existing validation
replay. A separate mocked-API regression checked active polling, preview failure,
stale pause responses and resume polling. No mock data was added to production UI.

## Regression results and changed files

- **93 backend tests passed:** activity rules/persistence, ROI/reference/fallback,
  source-time versus wall-time safety, replay endpoints and isolation, profile
  isolation, room/counting/camera routes, existing alert rules/persistence and
  Grill Gate registry authentication. Camera reconnect delay was shortened only
  in the test environment to fit an existing failure-test deadline.
- Frontend production build passed.
- Real-data UI/evidence checks and mocked polling regression passed.
- After loading the fixes on the idle main service (port 8010), both replay activity
  histories (4 and 5 records) and all their evidence were retrieved again. PostgreSQL
  contained zero production `VaultRoomAlert` rows for either validation replay or
  its internal room-session ID. Saved coordinates and the other four references
  were compared with the pre-change profile and remained equal.
- Simultaneous physical camera capture and the full unrelated Grill Gate suite
  were not rerun for this change. No Grill Gate, Entrance Camera, RF-DETR or
  ByteTrack implementation files were modified.

Files changed for this fix:

- `app/services/vault_region_monitor.py`: shared fallback membership.
- `app/services/vault_room_manager.py`: consistent observation, replay auth/timer
  and presence history; replay-local activity persistence/publication.
- `app/services/vault_room_replay.py`: local fallback profile, normalized session
  state/events, diagnostics and final writer-drained snapshot.
- `tests/test_vault_activity.py`, `tests/test_vault_room_replay.py`: regressions.
- Existing `var/vault-room-region-profiles/upload.json`: reference/version only;
  polygon coordinates preserved.
- Frontend `api/vaultRoom.js`, `hooks/useVaultRoomReplay.js`: explicit simulation,
  polling/mutation guards and independent status/image handling.
- Frontend `hooks/useVaultRoomRegions.js`, `components/vault/VaultRoomZones.jsx`:
  expose/preserve the configured reference.
- Frontend `components/vault/VaultRoomCameraControls.jsx`, `VaultRoomPanel.jsx`:
  replay-only authorization control and scoped-count explanation.
- This report and the activity API documentation clarify replay/live update scope.

Previously completed replays retain their old results; they are not rewritten or
backfilled with fabricated events. Refresh the page/profile and process the original
video again to use the corrected profile and code.
