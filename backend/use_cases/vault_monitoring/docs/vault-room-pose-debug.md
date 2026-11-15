# Replay Pose & ROI Debug

The Upload video controls on the Vault Room Camera tab now include **Show Pose &
ROI Debug**, default off. It can be switched during processing, pause or review
of the latest processed frame. Selecting a new file resets it. Zones & Regions,
Entrance, live camera controls and saved polygons are unchanged.

## Frame synchronization

The worker retains one small frame-local visualization snapshot alongside its
existing clean JPEG: pose results, accepted track matches, actual backend wrist
membership/progress/confirmed state, the exact backend Vault Area polygon and
confidence threshold. No additional inference or model is initialized.

`GET /api/v1/vault-room/video-sessions/{id}/frame?debug=true` atomically captures
the JPEG, snapshot, frame sequence and source timestamp, then renders the debug
JPEG on demand. `debug=false` (the default) returns the original clean JPEG.
Headers include `X-Replay-Session`, `X-Frame-Sequence`, `X-Video-Time` and
`X-Pose-Debug`; the debug image also prints its own sequence/time/session label.
No duplicate full-resolution debug frame is stored by the application.

The overlay shows matched skeletons, track IDs, L/R wrists (green inside, red
outside, neutral unreliable), the translucent Vault Area polygon, and actual
confirmation status. Unmatched current tracks have an explicit unavailable-pose
status. Wrist membership is the detector's result; visualization never recalculates
it. Reliable skeleton points use the same configured confidence threshold.
Cached/throttled or failed pose samples do not reuse older landmarks on a newer
image. ROI geometry remains available without a current pose.

Because markings are part of the selected JPEG, letterboxing, resize and fullscreen
scale the image and overlay together. Frontend mode changes invalidate in-flight
polls, clear the prior mode's image and immediately fetch the selected variant,
including for paused or completed replays. Failed image requests cannot combine
new pose metadata with an old image. Debug mode uses the frame's embedded source
time instead of displaying a potentially newer status-poll timestamp over it.

Existing processing/session/authorization state and event rules are unchanged.
Only visualization data is retained by the wrist monitor; it does not alter its
confirmation, rearming, matching or confidence decisions.

## Real recording validation

Recording: `temp/vault_authorized_employee_operation_30s_smooth.mp4`.
Completed replay: `68e09a60e5344535ba7b93ad4eefe27b`.

- All 144 sampled frames completed. The run took approximately 151 seconds under
  concurrent tests/debug requests, including an intentional pause. This is not
  a controlled comparison with earlier pipeline wall times.
- Events remained PERSON_DETECTED x3, PERSON_ENTERED x1, SESSION_STARTED x1,
  VAULT_AREA_ENTERED x0, VAULT_AREA_INTERACTION x1. No replay alerts occurred.
  All six evidence JPEGs were retrieved.
- Debug images at approximately 5.833, 6.875, 7.083 and 8.333 seconds were captured
  from the frame API. The 6.875 and 7.083 images were visually inspected.
  Pose dropout on the operating person correctly omitted that person's skeleton
  rather than showing an older estimate.
- At **frame sequence 35 / 7.083333 seconds**, Track 1's right wrist is inside
  the cabinet polygon with `CONFIRMED` status. The actual coordinates were
  `(0.706036, 0.768473)`, visibility `0.848729`, presence `0.893968`, and backend
  progress `1.25` seconds from five valid observations. These are the same source
  timestamp, track, hand and duration as the persisted interaction and its evidence.
  The overlay follows the correct operating person. Landmark localization remains
  a model estimate; the debug view is not proof of a real vault operation.
- While paused, repeated debug JPEGs and their frame headers were identical.
  Clean/debug requests shared the same frame sequence, and switching modes did
  not alter clean JPEG bytes or cause inference. Resume continued processing.
- Browser validation used this real replay's frame/status/activity/evidence APIs,
  binding launch requests to the existing run instead of duplicating inference.
  Default-off behavior, clean/debug switching, fullscreen, activity/evidence
  rendering and recovery from an injected preview-request failure passed.
- Saved profile data stayed unchanged; simulated authorization still started at
  1.25 seconds and the timer used source time. No production authorization or
  security alert records were written for the replay.
- The idle main backend was reloaded with its existing environment and launcher
  metadata preserved. All six events and evidence were retrieved on port 8010
  afterward, and the saved profile remained unchanged.

Debug request rendering (JPEG decode, overlay and re-encode) averaged **46.01 ms**,
median **44.65 ms**, across 180 validation requests under CPU load; the maximum
was 150.7 ms. Rendering occurs only for requested debug images. Off mode has no
debug render cost. Snapshot bookkeeping is lightweight; no additional MediaPipe
inference is performed for either mode.

## Checks and files

75 focused backend tests passed, including atomic snapshot selection during a
simulated concurrent publish, clean-output immutability, marker colors, and the
existing wrist, activity, replay, pose-preview, profile isolation and alert tests.
The final rendering/snapshot refinements also passed an 11-test targeted rerun.
The frontend production build passed with the existing bundle-size warning.

Backend paths relative to `backend/use_cases/vault_monitoring`:

- `app/services/vault_pose_debug.py`
- `app/services/vault_wrist_interaction.py`
- `app/services/vault_room_manager.py`
- `app/services/vault_room_replay.py`
- `app/api/routes/vault_room_replay.py`
- `tests/test_vault_pose_debug.py`
- `tests/test_vault_room_replay.py`
- `docs/vault-room-pose-debug.md`

Frontend paths relative to the repository root:

- `frontend/src/use-cases/vault-monitoring/api/vaultRoom.js`
- `frontend/src/use-cases/vault-monitoring/hooks/useVaultRoomReplay.js`
- `frontend/src/use-cases/vault-monitoring/components/vault/VaultRoomReplayPreview.jsx`
- `frontend/src/use-cases/vault-monitoring/components/vault/VaultRoomCameraControls.jsx`

An initial validation helper used case-sensitive header lookup and its unattended
paused test run hit the existing inactivity timeout. The helper was corrected and
the complete replay above was rerun successfully; no application timeout behavior
was changed.
