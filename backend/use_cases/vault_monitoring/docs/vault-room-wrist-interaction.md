# Vault Room replay wrist interaction

## Implementation

Uploaded replay now reuses `PosePreviewService` / MediaPipe Tasks Pose Landmarker
alongside the existing RF-DETR and ByteTrack pipeline. One lazy model instance
belongs to each replay worker and is closed with that worker. Live feeds and
Entrance authentication do not enable this wrist integration.

Replay supplies source-video milliseconds to `detect_for_video`. Source sampling
is independent of CPU/wall time, and cached or duplicate-timestamp results never
count as new observations. Each fresh worker starts with fresh pose and interaction
state. Existing interactive pose preview retains its wall-time throttling behavior.

`associate_poses` uses confident shoulders/hips as torso anchors and shoulders,
hips and elbows for person-box coverage. Candidates must have an anchor inside
the normalized ByteTrack box and at least 75% geometry coverage. Distance scores,
mutual best matching and a configurable ambiguity margin reject uncertain or
conflicting associations. A pose is never assigned to two tracks. Pose-list order
does not identify a person; wrists are allowed outside their person's body box.

Only finite, in-frame wrists with sufficient visibility **and** presence are
evaluated against the unchanged full-frame Vault Area polygon. Body entry is not
required. Confirmation is independent for each track/hand; only one event is
emitted during continuous interaction for a track. Both wrists must be reliably
outside for the configured exit duration before another interaction can fire.
Missing landmarks, unmatched poses and occlusion do not rearm a fired interaction.
Large observation gaps clear pending confirmation; a new track ID starts fresh.

The event is `VAULT_AREA_INTERACTION` with description
"Tracked person's wrist detected inside the Vault Area." Its existing activity
envelope carries session ID, source time, track IDs, zone ID, replay/test flags and
evidence reference. Metadata includes hand, interaction duration, valid observation
count, `mediapipe_pose_wrist_roi` detection method and simulated authorization.
It is an observation of wrist presence, not proof of opening, pickup or operation.
The existing `VAULT_AREA_ENTERED` body-position event is unchanged.

Persistence, evidence retrieval, API filtering and the existing Activity timeline
accept the new type. No security alert rule was added. The Camera tab still has
no ROI polygon overlay; the zone editor remains unchanged.

## Configuration and diagnostics

`vault_room.wrist_interaction` in `config/models.yaml` provides:

| Setting | Default |
| --- | --- |
| enabled | true, replay only |
| sampling_interval_ms | 200 source milliseconds |
| confirmation_seconds | 1 |
| exit_confirmation_seconds | 0.5 |
| min_observations | 3 |
| max_observation_gap_seconds | 0.75 |
| landmark_confidence | 0.5 for both visibility and presence |
| association_margin | 0.12 |
| diagnostics | false |

Sampling and maximum-gap settings must allow consecutive observations; sampling
more sparsely than the maximum gap cannot confirm an interaction. Missing pose
inference does not stop person processing or authorize a wrist event.

Lightweight replay state at `state.monitoring.pose` reports pose/match/unmatched
counts, model status and latency. With diagnostics enabled it additionally reports
pose-to-track mappings, unmatched indices/IDs, wrist coordinates/confidences,
membership and confirmation progress. These details are not rendered as camera
polygons. Validation enabled diagnostics only in its isolated server instance;
normal configuration remains false.

## Actual recording results

Input: `temp/vault_authorized_employee_operation_30s_smooth.mp4`, 1280 x 720,
24 FPS, 30 seconds, SHA-256
`96162fc1ac51bd11c1dc66649058ec6d89b13b2492e6815cff07e5445bec624b`.
Real inference replay ID: `bd35d21452ac4192869713ac442c9ea1`.

| Result | Observed |
| --- | --- |
| Completion | 144 sampled frames; 84.69 seconds wall time, including initialization |
| Confirmed person count | 2 |
| PERSON_DETECTED | 3 tracking episodes, including a later track replacement |
| PERSON_ENTERED | 1 |
| SESSION_STARTED | 1, source time 1.25 seconds, automatic simulated authorization |
| VAULT_AREA_ENTERED | 0; body reference points remain outside cabinet polygon |
| VAULT_AREA_INTERACTION | 1, source time 7.0833 seconds |
| Interaction details | Track 1, right wrist, 1.25 seconds, 5 valid observations |
| Simulated authorization on interaction | true |
| Replay alerts | 0 |
| Evidence | All 6 JPEGs retrieved successfully |
| Pose initialization | 4646 ms, once |
| Pose inference | Mean 47.03 ms, median 44.65 ms per sampled frame |
| Total processing | Mean 559.70 ms per sampled frame, including initialization |

Pose counts across sampled frames: zero on 11 frames, one on 89, two on 44.
There were 177 pose observations, of which 173 received accepted track matches;
4 remained unmatched. There were 91 unmatched track observations, principally
because MediaPipe did not return both people's poses during occlusion. The
173/177 acceptance ratio (97.7%) is **coverage, not measured identity accuracy**.
This recording has no manually annotated pose-to-track ground truth, so a formal
accuracy percentage is not claimed. Annotated overlays at approximately 1.25,
6.04, 7.08 and 20 seconds were inspected: torso matches followed the visible
people, including two simultaneous poses with reversed pose-list/track ordering.
The event-time overlay shows the operating person's right wrist inside the saved
cabinet ROI. No polygon or confidence threshold was changed to force an event.

The approximately 47 ms pose cost is a direct measured inference cost. Comparing
total wall time with earlier runs is not a controlled benchmark because CPU
load/model warmup differed. The timer continued using source time and did not
expire during slower processing.

## Verification

- 73 focused backend tests passed: wrist association, confidence/out-of-frame
  rejection, ambiguous matches, duplicate timestamps, source sampling, missing
  observations, confirmed exit/reentry, track replacement/session reset, durable
  event evidence independent of body entry, plus existing replay/authorization,
  profile isolation, alert and pose-preview tests.
- Frontend production build and all 3 activity utility tests passed. Existing
  ByteTrack deprecation and frontend bundle-size warnings remain.
- Browser validation bound launch requests to this real completed replay and read
  real status/activity/evidence APIs. Events (6), the wrist interaction and its
  full-resolution 1280-pixel evidence rendered without refresh. Automatic
  authorization and the source-time countdown remained visible. A transient
  preview-fetch failure did not block status updates.
- Saved upload profile before/after real inference was identical. Production
  authorization and security alert rows for the replay were both zero. Existing
  replay door-call guard tests passed; normal replay state remained locked.
- The idle main Vault backend was reloaded with its existing environment and
  launcher metadata preserved. All six durable events and their JPEG evidence
  were retrieved through port 8010 afterward, and the saved profile was unchanged.

## Files changed

Backend paths relative to `backend/use_cases/vault_monitoring`:

- `app/core/ml_config.py`
- `app/services/pose_preview.py`
- `app/services/vault_wrist_interaction.py`
- `app/services/vault_room_manager.py`
- `app/services/vault_activity.py`
- `config/models.yaml`
- `tests/test_vault_wrist_interaction.py`
- `tests/test_pose_preview.py`
- `tests/test_vault_activity.py`
- `docs/vault-room-wrist-interaction.md`

Frontend paths relative to the repository root:

- `frontend/src/use-cases/vault-monitoring/components/vault/VaultRoomPanel.jsx`
- `frontend/src/use-cases/vault-monitoring/utils/activityEvents.test.js`

No RF-DETR, ByteTrack, Entrance, Grill Gate, saved polygons, production alert
thresholds or door-controller implementation was changed. Start a new replay to
run pose integration; existing completed videos are not reprocessed automatically.
