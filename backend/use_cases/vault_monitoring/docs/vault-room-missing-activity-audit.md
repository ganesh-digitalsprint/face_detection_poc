# New Vault Room recording: activity persistence audit

## Finding: the interaction record is present

The exact reported query currently returns **five**, not four, durable activity
records for `450e773b3881407dbae405260dca1158`:

```text
GET /api/v1/vault-room/sessions/450e773b3881407dbae405260dca1158/activity-events
    ?source=upload&source_id=450e773b3881407dbae405260dca1158
    &replay=true&limit=25&offset=0
```

The supposedly missing record is:

- ID `93a3b3fe-2150-5a6d-8ddc-bfeca729ff81`.
- Type `VAULT_AREA_INTERACTION`, Track 1/right wrist, zone `vault_area_roi`.
- Source time **2.708333 seconds**, six valid observations over **1.041667 seconds**.
- Session, source and camera IDs all `450e773b3881407dbae405260dca1158`.
- Source `upload`, replay/test flags true, simulated authorization true.
- Evidence `a55cec5bed20f64aa1eb8ccb836daea2ba9d2ca0d0826ddd178fa053c050ccec`.
- Recorded at `2026-11-12T18:53:06.644099Z`, which is **13 November 2026,
  00:23:06 IST**. The first four events were created around 00:23:00 IST.

Direct database inspection found five activity-channel rows. Filtered and unfiltered
API reads, event-type filtering, limit-two pagination, ordering and all evidence
requests agreed. Wrong-source filters returned zero. No pending activity outbox
batch or current writer error was found for this session. Its temporary replay
has been deleted (the access log contains DELETE 200), explaining status GET 404;
its durable activity and evidence remain accessible.

The screenshots identify a **different replay**, prefix `524f3a00`, resolved in
the access logs to `524f3a00784848cc8a7ee71b63b48c35`. That session also has five
database/API records and a wrist interaction at 2.708333 seconds. The screenshot
therefore cannot establish the current API contents of the separately named
`450e...` session. No frontend cache crossover was reproduced; the existing
context/generation guards were preserved.

**No missing database/API record was reproduced, so no persistence trigger was
added.** The timestamp/body of the original four-record response was not provided;
its precise historical origin cannot be proven. Four records are a valid earlier
snapshot before the wrist event commits, which the fresh replay reproduced.
Treating that earlier response or a different replay's screenshot as the current
complete persisted result creates the apparent discrepancy.

One concrete frontend defect was verified: commit invalidation selected the
**oldest** matching `activity.created` notification. Later commits did not change
that selected ID, so an immediate refresh could be missed until the existing
three-second polling interval. It now selects the latest matching notification
and checks session, source, source ID and replay mode. This fixes refresh latency;
it is not evidence that the already-existing database record was lost.

## Event lifecycle and confirmed-state meaning

1. The replay decodes a source frame and runs unchanged RF-DETR / ByteTrack and
   the existing MediaPipe Full worker.
2. The region monitor evaluates body membership; the wrist monitor separately
   associates poses, checks confidence and evaluates the cabinet ROI.
3. A confirmed wrist emits one operational event and queues an `ActivityEvent`
   with a deterministic session/sequence ID and a copy of that frame.
4. The existing writer encodes content-addressed JPEG evidence, creates its durable
   pending batch, inserts the activity into `vault_room_events` under
   `channel: activity`, and commits the database transaction.
5. Only after commit does it publish `activity.created`. The existing activity API
   reads those database records; the frontend refreshes/polls the scoped endpoint.

The debug overlay's `CONFIRMED` is an interaction-episode latch, **not a database
commit acknowledgement**. Screens at 4.167 or 10 seconds can retain the episode
confirmed at 2.708 seconds without emitting another event. Missing or unreliable
wrists do not generate new events or automatically rearm that latch.

The writer is asynchronous. An operational event/confirmed overlay can precede
the corresponding committed API row briefly. A new regression test deliberately
blocks the fifth write: filtered storage stays at four while diagnostics say
QUEUED, then becomes five with PERSISTED status and evidence after commit.

## Body-entry result

All 120 captured frame snapshots retained the exact selected **upload profile
version 4**. No saved configuration was changed by this task. Vault Area uses
`bottom_center`, one-second confirmation and at least two valid samples.

At 2.708333 seconds:

| Track | Bounding box (normalized xyxy) | Bottom-center point | Inside Vault Area |
| --- | --- | --- | --- |
| 1 | 0.50136, 0.15279, 0.81215, 0.99091 | 0.65675, 0.99091 | No |
| 2 | 0.08019, 0.14379, 0.34515, 0.98908 | 0.21267, 0.98908 | No |

Checks at 4.167, 10 and 20 seconds likewise reported BODY_REFERENCE_OUTSIDE,
zero pending samples and zero confirmation duration. The cabinet polygon ends
above those body reference points. A valid wrist inside it does not imply that a
person's body entered it. `VAULT_AREA_ENTERED` is therefore correctly absent.
If person operating-space entry is required, define a separate standing/operating
area during a region-design change; retain the cabinet ROI for wrist interaction.
No geometry, reference choice or new region key was silently substituted here.

## Event audit

| Event type | Implemented? | Detection evidence / responsible service | Trigger result | Persistence result | Root cause | Fix required |
| --- | --- | --- | --- | --- | --- | --- |
| PERSON_DETECTED | Yes | RF-DETR + ByteTrack, `VaultRegionMonitor` stable ROI presence | Two confirmed tracks | Two rows | Working | None |
| PERSON_ENTERED | Yes | Existing stable two-track presence confirmation; not a doorway-crossing claim | Once at 1.25 s | One row | Working | None |
| SESSION_STARTED | Yes | Replay-only simulated two-person authorization after presence confirmation | Once at 1.25 s | One row | Working | None |
| VAULT_AREA_INTERACTION | Yes | MediaPipe Full reliable right wrist + `WristInteractionMonitor` ROI/time/sample rules | Once at 2.708 s | One row, evidence accessible | Not currently missing; supplied evidence mixes sessions/earlier snapshots; notification refresh defect verified | Latest-commit refresh fixed; diagnostics added, no trigger change |
| VAULT_AREA_ENTERED | Yes | Tracked body reference + `VaultRegionMonitor` polygon/duration rule | Not satisfied | No row expected | Body reference outside cabinet polygon | Separate operating-space geometry/design if body entry is required |
| VAULT_OPEN_DETECTED | No | Needs observed door open/closed transition; no connected Vault replay door-state detector | Not evaluated | No row | Missing functionality, not a dropped write | Door-state visual detector/classifier or independently verified sensor signal plus temporal transitions |
| ORNAMENT_REMOVAL_DETECTED | No | Needs ornament presence/identity before and after removal; no connected ornament detector | Not evaluated | No row | Missing functionality | Object presence/inventory model or validated change detection, occlusion handling and temporal state |
| TRAY_INTERACTION | No | Needs reliable hand-to-tray evidence; no connected tray-interaction service | Not evaluated | No row | Missing functionality | Tray localization and hand/object association with confirmation |
| VAULT_LOCK_DETECTED | No | Needs lock engagement evidence; no connected lock-state detector | Not evaluated | No row | Missing functionality | Validated lock-state signal/model and transition confirmation; door closed alone is insufficient |
| TRAY_PICKUP_DETECTED | No | Needs tray identity/movement and hand relationship; no connected tray tracking/pickup service | Not evaluated | No row | Missing functionality | Tray detector/tracker and supported/moving/lifted state machine |

These five unsupported names have no registered activity type or connected
emission path in this Vault replay implementation. The frontend category test
mentioning a future door event does not implement it. The recording can show
motion/reaching, but available person boxes and pose wrists cannot establish
ornament inventory, tray pickup or a mechanical lock state. Region polygons only
configure locations; they do not create object detectors. No five additional
event types were implemented or fabricated. Their models/signals require a
separate reviewed specification and validation data.

## Optional diagnostics

The existing replay-only `wrist_interaction.diagnostics` flag remains **false by
default**. When enabled it now additionally records, per processed source frame:

- Session/frame/source time, active session state, simulated authorization and
  confirmed count, alongside existing pose matches/rejection/confidence details.
- Body boxes, actual reference points, exact polygon, membership, sample/time
  thresholds and suppression reason.
- Person-presence confirmation latch and wrist pending samples/duration/dedup state.
- Evaluated/emitted event types and a bounded event-ID ledger with QUEUED,
  PERSISTED or FAILED, evidence reference, source/track/zone IDs, error class and
  status timestamp. A failed write is not reported as persisted.

State exposes this under `monitoring.activity_conditions` / `activity_writes`;
the same data is optionally logged. Existing activity outbox/transaction behavior
is preserved. No production logging expansion occurs with the flag disabled.

## Fresh recording validation

Source: `temp/vault_monitoring_hand_raise_updated_25s.mp4`.
SHA-256: `be7a0e0781991302efc232ab9553bdf9cf048a89542ab3f30d5ec6d28c3debde`.
Decoded metadata: **1280 x 720, 24 FPS, 599 frames, 24.958333 seconds**.
New replay ID: `3b26e573feb242ecb4bbc771592b4f5b`; it was kept distinct from both
original sessions in every query and test.

- Entire recording completed: 120 sampled frames, about 134 seconds wall time
  including startup, diagnostic recording, pause, browser checks and concurrent tests.
- Tracks 1 and 2 remained confirmed; two PERSON_DETECTED, one PERSON_ENTERED,
  one SESSION_STARTED, one VAULT_AREA_INTERACTION, zero VAULT_AREA_ENTERED.
- The interaction reproduced at 2.708333 s for Track 1/right wrist, six valid
  observations over 1.041667 s. Its JPEG checksum exactly matches the original
  `450e...` event above, connecting the reproduction to that source frame.
- Filtered API polling recorded totals 0, then 4, then 5. All final ledger entries
  were PERSISTED; direct database/API reads returned five. Limit-two pagination,
  stable ordering, event-type filtering and wrong-session/source exclusions passed.
- All five JPEGs loaded, with correct IDs, timestamps, track/ROI association,
  replay/test flags and source ID. The actual event frame was visually inspected.
- Browser checks used real status/frame/activity/evidence/control APIs (launch
  requests bound to the existing validation replay). Five events, wrist evidence,
  debug switching, fullscreen, preview-failure recovery and pause/resume passed.
- No alerts, production authorization rows or production security alert rows were
  created for the test. Full model selection and saved profile remained unchanged.
- The idle main backend was reloaded with its existing environment preserved.
  The five records and evidence were retrieved again on port 8010 afterward;
  the profile was unchanged. Temporary validation runtime cleanup does not delete
  these durable activity records.

Tests: **83 backend tests passed**, **4 frontend activity utility tests passed**,
and frontend production build passed. Regression coverage includes latest scoped
commit invalidation, queued-versus-committed four-to-five retrieval, writer failure
diagnostics, unchanged replay isolation and existing pose/ROI/event/evidence rules.
Existing ByteTrack deprecation and bundle-size warnings remain.

## Exact files changed

Backend paths relative to `backend/use_cases/vault_monitoring`:

- `app/services/vault_room_manager.py`
- `app/services/vault_room_replay.py`
- `app/services/vault_region_monitor.py`
- `tests/test_vault_activity.py`
- `docs/vault-room-missing-activity-audit.md`

Frontend paths relative to the repository root:

- `frontend/src/use-cases/vault-monitoring/hooks/useVaultActivityEvents.js`
- `frontend/src/use-cases/vault-monitoring/utils/activityEvents.js`
- `frontend/src/use-cases/vault-monitoring/utils/activityEvents.test.js`

No detection/authorization/event trigger, API filter, database schema, saved polygon,
model selection, real door integration, production alert rule, Entrance or Grill
Gate behavior was changed. The shared activity hook change fixes a conclusively
identified notification-selection bug; its existing polling and context guards remain.
