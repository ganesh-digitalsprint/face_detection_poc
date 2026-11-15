# Independent uploaded-replay ROI interactions

The fixed Vault / Door / Ornament / Tray workflow has been removed from the
replay-only `VaultWorkflowMonitor`. Its existing class and configuration key are
retained for integration compatibility. There is no expected stage, operator
lock, ROI winner, previous-event prerequisite or session-wide ROI event limit.

Door, Ornament Area and Tray Area each evaluate current, reliably associated
wrists independently, including overlapping memberships. State is isolated by
track ID, wrist side and ROI. The existing Vault Area interaction detector is
unchanged and continues running separately.

Confirmation uses 0.5 source-video seconds and at least three positive samples;
confirmed exit uses 0.5 seconds and three reliable outside samples. Dropout
tolerance remains 0.5 seconds. Missing/unreliable observations cannot emit or
confirm exit. Short gaps may retain pending observations but never add samples;
longer gaps clear pending confirmation. Confirmed episodes remain latched through
pose/track loss until reliable exit is confirmed. A new track cannot inherit state.
The settings model's fallback now also matches the existing 0.5-second YAML value.

The manager still constructs this monitor only for uploaded replay workers.
Person detection, body membership, simulated authorization, the original wrist
detector, models and event writer were not modified.

## Actual recording result

Input: `temp/vault_monitoring_hand_raise_updated_25s.mp4`.
SHA-256: `be7a0e0781991302efc232ab9553bdf9cf048a89542ab3f30d5ec6d28c3debde`.
1280 x 720, 24 FPS, 599 frames. All 120 sampled frames completed.
Fresh session: `3cf903191a904ad38f1812ac67591d26`.

**11 durable activity records:** the original five, plus two Door, two Ornament
Area and two Tray interactions. Exact API order is shown below. Simultaneous
events retain the existing creation-time / deterministic-ID tie order; no event
type or ROI ranking is applied to the timeline.

| Source time (s) | Persisted activity | Track / wrist |
| --- | --- | --- |
| 1.250000 | PERSON_ENTERED | 1, 2 |
| 1.250000 | PERSON_DETECTED | 1 |
| 1.250000 | PERSON_DETECTED | 2 |
| 1.250000 | SESSION_STARTED | 1, 2 |
| 2.291667 | ORNAMENT_AREA_INTERACTION | 1 / right |
| 2.291667 | VAULT_DOOR_INTERACTION | 1 / right |
| 2.708333 | VAULT_AREA_INTERACTION | 1 / right |
| 8.541667 | ORNAMENT_AREA_INTERACTION | 1 / right |
| 10.000000 | TRAY_INTERACTION | 1 / right |
| 11.666667 | VAULT_DOOR_INTERACTION | 1 / right |
| 19.375000 | TRAY_INTERACTION | 1 / right |

Each of the six new interactions had four actual reliable observations spanning
0.625 seconds. At this sampled cadence, four observations are needed to exceed
0.5 seconds. All six were matched against the captured source frame, actual wrist
confidence/coordinates and exact saved polygon. All 11 evidence JPEGs loaded;
the six new event images and the independent debug panel were visually inspected.

Door and Ornament legitimately share the first confirmation frame. This reports
two polygon memberships, not verified door opening or ornament removal. The
later Door interaction likewise describes the saved projected polygon, not an
independently verified mechanical operation. Every new interaction carries
`physical_operation_verified: false` and uses the existing durable writer.

## Episode and rejection findings

| ROI | Confirmed wrist exits | Result |
| --- | --- | --- |
| Door | 10.000000, 17.916667 s | Two distinct confirmed episodes |
| Ornament Area | 6.875000, 10.000000 s | Two distinct confirmed episodes |
| Tray Area | 14.791667, 21.041667 s | Two distinct confirmed episodes |

No requested interaction type is missing from this run. Track 1's left wrist had
15 reliable outside samples and no inside samples. Track 2's left wrist had seven
reliable outside samples and no inside samples; its right wrist had no reliable
current observations. Those wrists generated no proxy events. Unreliable/missing
samples were rejected; continuous inside episodes were suppressed only for the
same track/wrist/ROI after emission. Overlapping ROIs did not suppress each other.

`VAULT_AREA_ENTERED` remains absent because the unchanged body reference is outside
the cabinet polygon. Wrist interactions do not force body entry. Existing Vault
Area interaction remains at 2.708333 seconds. No polygons were changed.

## Debug, persistence and UI checks

Debug mode now shows each track and wrist's Door / Ornament / Tray state
(`WAITING`, `PENDING`, `CONFIRMED`, `REARMING`), memberships, duration, sample count,
last emitted event and exact rejection reason. It explicitly distinguishes
emission from database commitment. There is no ordered-stage display.
Clean playback and the existing person/pose/ROI visualization paths are preserved.

Validation used an isolated listener with the existing service environment. A
temporary wrapper captured all 120 monitor calls without additional inference.
Pause/resume held the same source frame, repeated debug fetches were identical,
and clean frame bytes remained unchanged by debug toggling.

The browser used real committed API records, binding launch calls to the already
completed replay to avoid duplicate inference. Read-only visibility was staged
as 4, 5, 6, then 11 records to deterministically test polling append behavior.
Previously visible rows retained their positions. Full UI/API order, manual
refresh, page reload, the expanded Event Log and 1280-pixel evidence viewer passed.

The idle main service was reloaded with its environment preserved. Port 8010
returned the identical 11 durable records. The upload profile was unchanged;
there were zero replay alerts, zero production alert rows and zero production
authorization rows for this session. The temporary validation runtime was then
removed; persisted activity and evidence remain available.

## Regression checks and files

54 backend tests passed across independent interactions, wrist association,
pose debug, replay lifecycle and activity persistence. Coverage includes arbitrary
order, overlap, repeated exit/re-entry, dropouts, unreliable/unmatched wrists,
track/hand/session isolation, unchanged live behavior and asynchronous commits
for all three new interaction types. Six frontend timeline tests also passed.
The existing ByteTrack deprecation warning remains.

Files changed (backend paths relative to `backend/use_cases/vault_monitoring`):

- `app/services/vault_workflow.py`
- `app/services/vault_pose_debug.py`
- `app/core/ml_config.py` (replay workflow fallback only)
- `tests/test_vault_workflow.py`
- `tests/test_vault_activity.py`
- `tests/test_vault_pose_debug.py`
- `docs/vault-room-independent-roi-interactions.md`

No frontend, live authorization, security-alert rules, Entrance Camera, Grill
Gate, detector/tracker, model selection, saved-region or persistence implementation
was changed for this task. Earlier ordered-workflow reports describe historical
behavior and are superseded by this independent-monitoring report.
