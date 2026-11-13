# Automatic uploaded-replay authorization

## Cause and corrected flow

Replay previously started through `on_access_granted` and exposed a manual
simulated-authorization checkbox. That coupled processing startup to an access
grant while leaving `SESSION_STARTED` dependent on an opt-in flag.

`POST /api/v1/vault-room/video-sessions/{session_id}/start` now starts inference
with an isolated, unverified replay context. Omitting `simulated_authorization`
enables automatic replay simulation. Two distinct current ByteTrack tracks must
meet the existing stable-count and Person Monitoring Area duration/sample rules,
with exactly two people expected, before authorization becomes `SIMULATED`.
The six-minute source-time session starts then, once. Its activity metadata includes
`simulated_authorization: true`,
`authorization_method: SIMULATED_TWO_PERSON_PRESENCE`, and
`real_identity_verified: false`.

No access-grant callback is invoked by replay startup. Replay guards also prevent
door-controller calls when starting, closing, or timing out. Live authorization
and actuator paths are unchanged. Replay processing and authorized session state
remain separate, and wall time does not advance the video timer.

For API compatibility, explicit `false` retains the old unverified replay test
path; explicit `true` also waits for confirmation. The frontend sends neither
option and replaces the checkbox with a read-only pending/active status. A
one-person expected-count replay can still process but cannot obtain simulated
two-officer authorization.

## Vault Area finding

The saved upload profile remains version 2. All five regions, reference settings,
and polygon coordinates were preserved byte-for-byte at the API level. The Person
Monitoring Area already uses `center`; Vault Area uses `bottom_center` with a
one-second confirmation duration.

The Vault Area polygon encloses the cabinet, not the floor/operating space.
At source time approximately 1.04 seconds, actual tracked bottom-center points
were `(0.4905, 0.9923)` and `(0.2467, 0.9057)`; both are outside that polygon.
Checks around 5, 10, 15, 20 and 25 seconds likewise found both points outside.
Empty membership is consistent with the saved geometry, not a coordinate
normalization or tracking failure. No event was forced to satisfy an expected
count.

To monitor a person operating the vault with bottom-center membership, redraw
Vault Area over the visible standing/operating space in the existing editor.
For this cropped upper-body view, an explicitly selected center reference and
appropriate operating-space polygon is another configurable option. This fix
does not make either change automatically. Object-region configurations remain
independent and unchanged; no new object-interaction detection was added.

Vault entry confirmation uses the existing `VAULT_AREA_ENTERED` event contract,
track/zone IDs, source timestamp, evidence and duration/deduplication rules.
It now distinguishes `entry_kind: initial_occupancy` from `observed_entry`, with
explicit `initial_occupancy`/`observed_entry` booleans and an accurate description.
Initial occupancy is not described as an observed crossing. Leaving the region
allows a subsequent confirmed entry; continuous occupancy does not duplicate it.

## Actual recording and browser validation

Recording: `temp/vault_authorized_employee_operation_30s_smooth.mp4`,
1280 x 720, 24 FPS, 720 frames, 30 seconds. SHA-256:
`96162fc1ac51bd11c1dc66649058ec6d89b13b2492e6815cff07e5445bec624b`.

Replay `a73aa150647946e58a86500bd600fde9` ran the real decoder, RF-DETR,
ByteTrack, saved profile, counter, activity persistence and replay alert pipeline.
The start request omitted the simulation flag. A separate validation listener
avoided disturbing live monitoring during inference.

| Check | Result |
| --- | --- |
| Processing | Completed, 144 sampled frames, about 126 seconds wall time |
| Before confirmation | Pending simulation, verified count 0, no authorized timer |
| Confirmed people | 2 |
| Automatic session start | Exactly once, source time 1.25 seconds |
| Session timer | Starts at 360; final 331 seconds at source time 29.7917 |
| PERSON_DETECTED | 3 tracking episodes (later track replacement is not a third identity) |
| PERSON_ENTERED | 1 |
| SESSION_STARTED | 1, simulated metadata, real identity false |
| VAULT_AREA_ENTERED | 0; actual reference points outside saved polygon |
| Replay alerts | None; no unauthorized, no-entry or expiry alerts |
| Evidence | All 5 JPEGs retrieved successfully |
| Door state | Locked throughout; no SESSION_GRANTED event |
| Production records for replay | 0 security alerts, 0 authorization session rows |

Browser verification used real status/activity/evidence/control responses for
this replay, binding launch requests to the already-running validation session
instead of starting duplicate inference. It showed 2 of 2 people, read-only
simulated authorization, source-time countdown, Events (5), and full-resolution
evidence without refresh. Pause/resume held source time; polling recovered from
an injected preview-fetch failure. The screenshot was inspected for alignment.

The idle main Vault service was reloaded with its existing environment. All five
events and evidence were retrieved again through port 8010 after restart, and
the saved profile remained unchanged. Existing completed replays are not
backfilled; start a new processing run to use the automatic workflow.

## Automated checks

- 59 focused backend tests passed across activity events, replay lifecycle,
  profiles, region isolation, room manager and alert rules. Tests cover zero,
  one and three people never authorizing; two-person confirmation/deduplication;
  source-time behavior; initial occupancy versus observed entry; evidence
  persistence; production isolation; and a door stub that fails on any call.
- Frontend production build passed. Existing bundle-size and ByteTrack
  deprecation warnings remain.
- No Entrance, Grill Gate, detector, tracker, production thresholds or region
  storage implementation was changed for this task.

## Files changed for this task

- `app/api/routes/vault_room_replay.py`
- `app/services/vault_room_replay.py`
- `app/services/vault_room_manager.py`
- `app/services/vault_region_monitor.py`
- `tests/test_vault_activity.py`
- `tests/test_vault_room_replay.py`
- `frontend/src/use-cases/vault-monitoring/api/vaultRoom.js`
- `frontend/src/use-cases/vault-monitoring/hooks/useVaultRoomReplay.js`
- `frontend/src/use-cases/vault-monitoring/components/vault/VaultRoomCameraControls.jsx`
- `frontend/src/use-cases/vault-monitoring/components/vault/VaultRoomPanel.jsx`
- `docs/vault-room-replay-processing-fix.md` (superseded-workflow notice)
- `docs/vault-room-auto-authorization.md` (this report)

Backend paths above are relative to `backend/use_cases/vault_monitoring`;
frontend paths are relative to the repository root. Runtime service reload also
updated ignored launcher metadata and logs, without changing launcher code.
