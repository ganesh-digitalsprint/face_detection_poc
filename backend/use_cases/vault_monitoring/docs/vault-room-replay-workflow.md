# Replay-only observed ROI workflow

## Implemented behavior

`VaultWorkflowMonitor` consumes the current matched wrist observations already
produced by MediaPipe Full / `WristInteractionMonitor`, confirmed presence and
the existing simulated-authorization state. It runs only on uploaded replay
workers. No new inference, model, association, body-reference rule or authentication
decision is introduced.

The activity schema accepts three new **observed interaction** types:

- `VAULT_DOOR_INTERACTION`
- `ORNAMENT_AREA_INTERACTION`
- `TRAY_INTERACTION`

They are not assertions of opening, removal, locking or pickup. Their descriptions
say the physical operation is unverified, and metadata includes
`physical_operation_verified: false`. No security alert or access-control rule
uses them. The unsupported physical-operation event types from the previous
audit remain unsupported; the earlier audit's TRAY_INTERACTION status is superseded
by this explicitly observed implementation.

The replay workflow observes existing two-person confirmation and simulated
authorization, then waits for the existing `VAULT_AREA_INTERACTION` event. The
first authorized confirmed track becomes the workflow operator. Subsequent
progression is Door -> Ornament -> Tray -> Door -> Tray. A deterministic track-ID
tie break applies if multiple initial Vault confirmations arrive together. The
engine does not infer identity from shirt color or automatically transfer progress
to a replacement ByteTrack ID.

Per-track/per-hand state keeps ROI exit observations separate. Other people's
wrists cannot advance the selected operator's workflow. New workers start empty.
An original Vault interaction occurring before authorization does not seed an
authorized workflow retrospectively.

## Overlap and episode rules

Every reliable wrist is checked against all four saved interaction ROIs in the
same full-frame normalized coordinate system. Only the expected stage may emit.
Among overlapping memberships, the smallest polygon area has spatial priority;
equal-area tie priorities are Ornament, Tray, Door, Vault. A more specific ROI
suppresses an overlapping broader stage rather than emitting both.

If the next ROI is already occupied, was still in an active episode, or has
unknown membership when a stage completes, that wrist must show a confirmed
outside interval before re-entry can qualify. An initial outside observation for
a previously unoccupied ROI can establish a subsequent first entry. A confirmed
ROI's prior participating wrist must also exit before a later occurrence can
reuse that region. A one-frame boundary flicker or pose disappearance is not exit.

Only one stage can advance per source frame. The same continuously occupied
overlapping ROI cannot be reused to create successive stages. A later genuine
entry into a different target can qualify even if a broad parent region still
contains the wrist. Out-of-order observations are diagnosed/suppressed; they are
not buffered and replayed later as if they occurred in the required order.

Missing, stale, unmatched, low-confidence and out-of-frame wrist positions never
count as positive observations. A short dropout may preserve pending state, but
cannot emit an event. Confirmation is evaluated only on a new valid observation;
gaps beyond the tolerance reset pending observations. Missing samples do not
release exit gates or fabricate a wrist position.

## Configuration

New `vault_room.workflow` settings in `config/models.yaml`:

| Setting | Default |
| --- | --- |
| enabled | true; instantiated only for replay |
| confirmation_seconds | 1.0 |
| min_observations | 3 |
| exit_confirmation_seconds | 0.5 |
| exit_min_observations | 3 |
| dropout_tolerance_seconds | 0.5 |

These settings govern the new ordered interaction confirmations. Existing wrist
and body event settings are unchanged. Existing wrist visibility and presence
thresholds are reused; they were not lowered.

## Persistence and visualization

New events pass through the same `RoomEvent` / `ActivityEvent` pipeline, durable
writer, evidence spool and existing activity endpoints as earlier events. The
existing JSON activity envelope requires no database migration or duplicate API.
It provides session/source/track/ROI IDs, source-video timestamp, replay/test flags
and evidence JPEG. New metadata includes wrist side, visibility, presence, wrist
coordinates, duration, valid sample count, workflow stage, candidate/selected ROIs
and unverified-operation semantics.

The existing Activity Events timeline displays the new names/descriptions and
evidence. Raw workflow event copies are excluded from the auxiliary legacy
timeline, avoiding duplicate presentation. Existing activity filters categorize
observed Door interaction under Door and Ornament/Tray interactions under Activity.

Pose & ROI Debug adds a compact workflow panel: operator track, current stage,
current left/right memberships, pending duration/sample count, last confirmed
interaction and suppression reason. It is part of the existing atomic frame
snapshot and on-demand debug JPEG. Clean images, all five ROI polygons, pose
visualization, source-time alignment, fullscreen and paused playback are preserved.
The Zones & Regions editor is unchanged.

## Actual 25-second recording result

Input: `temp/vault_monitoring_hand_raise_updated_25s.mp4`.
SHA-256: `be7a0e0781991302efc232ab9553bdf9cf048a89542ab3f30d5ec6d28c3debde`.
1280 x 720, 24 FPS, 599 source frames / 24.958333 seconds.
Completed validation replay: `f2260c224e384a568af44c7de16f16ea`.
All 120 sampled frames completed in about 50.8 seconds including initialization,
pause and diagnostic/API requests; this is not a controlled speed benchmark.

| Workflow stage | Actual outcome |
| --- | --- |
| 1. Two people confirmed | Confirmed at 1.25 s; Tracks 1 and 2 |
| 2. Simulated authorization | Existing SESSION_STARTED at 1.25 s |
| 3. Vault interaction | Existing VAULT_AREA_INTERACTION at 2.708333 s, Track 1/right wrist |
| 4. Door interaction | New VAULT_DOOR_INTERACTION at **15.208333 s**, Track 1/right wrist |
| 5. Ornament area interaction | **Not confirmed** after eligible Door stage |
| 6. Tray interaction | **Blocked** by missing ordered Ornament stage |
| 7. Subsequent Door interaction | **Blocked** by earlier incomplete stages |
| 8. Subsequent Tray interaction | **Blocked** by earlier incomplete stages |

The new Door event used six reliable observations over 1.041667 source seconds.
Visibility was 0.90849, presence 0.99432, wrist `(0.722533, 0.562729)`. Both Vault
and Door were candidates, Door had the more specific polygon, and Ornament was
not occupied at confirmation. Its evidence reference is
`ca362c9d358c408a5e4ff72c0f5f824ced0641492ded412969c71133150ac875`.
The actual debug/evidence frame was inspected; it shows the correct operator's
wrist in the Door ROI. The event does not claim opening or locking.

The initial Vault confirmation already overlapped nested cabinet regions. Counting
that same held wrist as Vault, Door and Ornament in immediate succession would
invent distinct workflow episodes. The engine therefore waited for an actual
exit/re-entry and eligible Door-specific evidence. Earlier tray/ornament-looking
observations did not satisfy the required stage order and were not backdated.
After Door confirmation, reliable wrists were outside the Ornament ROI or
unavailable; no Ornament confirmation samples accumulated. The workflow therefore
ends waiting at stage 5. **The recording did not confirm the complete eight-stage
workflow under these geometry/episode rules.** No timestamps, captions or expected
physical-operation timeline were used as triggers.

Final persisted event counts:

| Event | Count |
| --- | ---: |
| PERSON_DETECTED | 2 |
| PERSON_ENTERED | 1 |
| SESSION_STARTED | 1 |
| VAULT_AREA_INTERACTION | 1 |
| VAULT_AREA_ENTERED | 0, unchanged body-reference geometry |
| VAULT_DOOR_INTERACTION | 1 |
| ORNAMENT_AREA_INTERACTION | 0 |
| TRAY_INTERACTION | 0 |

All five earlier records preserved their exact source times, track IDs, ROI IDs
and evidence checksums compared with the prior recording run. The sixth record
is the new observed Door event. Six unique IDs, six JPEG evidence reads, scoped
filters and limit-two pagination were verified. Every captured frame retained
the exact saved profile version 4 polygons. There were no replay alerts or
production authorization/security-alert rows for this replay.

Browser validation used real status, activity, frame, evidence and control APIs,
binding launch requests to the existing run instead of duplicating inference.
The UI showed Events (6), the new Door event and its full-resolution JPEG. Debug
switching, fullscreen, failed-preview recovery and pause/resume passed. The main
backend was reloaded before new event types were persisted and independently
returned all six records and JPEGs through port 8010.

## Tests

- **89 backend tests passed** across workflow, activity/evidence, wrist, replay,
  profile isolation, pose preview, room manager and alert-rule suites.
- Regression cases cover a complete supported ordered workflow; overlapping and
  identical ROIs; a nested next ROI remaining occupied; source-time confirmation;
  missing/unreliable wrists; no stale-positive samples; boundary flicker; confirmed
  exit/re-entry; out-of-order observations; track-ID changes; duplicate timestamps;
  replay isolation; and durable evidence for all five synthetic ordered stages.
- The integrated synthetic sequence verified five new events at stages 4–8,
  including repeated Door/Tray types, with one existing pose inference call per
  frame and no workflow on the live parent manager.
- **4 frontend utility tests and the production build passed.** Existing ByteTrack
  deprecation and frontend bundle-size warnings remain.

## Exact files changed

Backend paths relative to `backend/use_cases/vault_monitoring`:

- `app/core/ml_config.py`
- `app/services/vault_workflow.py`
- `app/services/vault_activity.py`
- `app/services/vault_room_manager.py`
- `app/services/vault_pose_debug.py`
- `config/models.yaml`
- `tests/test_vault_workflow.py`
- `tests/test_vault_activity.py`
- `docs/vault-room-replay-workflow.md`

Frontend paths relative to the repository root:

- `frontend/src/use-cases/vault-monitoring/components/vault/VaultRoomPanel.jsx`
- `frontend/src/use-cases/vault-monitoring/utils/activityEvents.test.js`

No RF-DETR, ByteTrack, MediaPipe model/threshold, saved polygon, original event
trigger, authorization/timer, production alert, Entrance or Grill Gate code was
changed. Start a new replay to use the new worker workflow state.
