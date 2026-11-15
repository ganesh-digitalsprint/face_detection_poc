# Vault Room replay pose stability investigation

## Actual failure and limits

The original recording produced 177 Lite pose observations across 144 sampled
frames, but 264 confirmed ByteTrack person/frame observations. MediaPipe often
returned only one person's pose while ByteTrack retained both people. The original
matcher accepted 173 poses; two genuine geometry rejections were recovered at
25.833 and 26.042 seconds by prioritizing torso geometry over extended elbows.
The other two unmatched pose observations occurred without a confirmed track.
Eleven frames had no returned pose; these were not evidence of an association
failure. Matching cannot recover landmarks that MediaPipe never returned.

The old overlay combined all these cases under "pose unmatched". It also had
no per-track pose age or missing-sample state. This task separates missing model
output, rejected associations, unreliable wrists and reliable wrists outside ROI.

## Changes

- Matching uses reliable shoulders/hips, torso center, box coverage and normalized
  spatial distance. Extended elbows no longer veto otherwise valid torso geometry.
  Recent per-track torso/box geometry contributes a small continuity score, never
  a pose-list index or wrist-only identity guess. Mutual one-to-one matching and
  ambiguity rejection remain. History alone cannot resolve indistinguishable poses.
- Per-track state records last valid pose time, wrist observations, geometry score,
  reliable ROI membership, missing-sample count and status: OBSERVED,
  TEMPORARILY_MISSING, UNMATCHED, UNRELIABLE or LOST. Geometry scores are ranking
  scores, not calibrated probabilities, and can slightly exceed 1 with continuity.
- `dropout_tolerance_seconds: 0.5` is configurable in `wrist_interaction`. A short
  gap can preserve a pending episode, but missing samples never add positive
  observations or emit an event. A new reliable inside observation is required
  to resume and evaluate source-time confirmation. A gap beyond tolerance clears
  pending confirmation and stale wrist caches. Confirmed-event deduplication stays
  latched until the existing confirmed-exit rule; disappearance is not treated as exit.
- No cached wrist is drawn as a current detection. Current invalid wrists are
  neutral; unmatched tracks show their actual reason and last pose age. Current
  wrists show visibility/presence, inside/outside and confirmation progress. All
  five profile polygons remain visible. Debug snapshots deep-copy temporal state
  so later observations cannot alter an earlier frame's diagnostics.
- Full diagnostics are available in replay state/frame snapshots. Enabling the
  existing `wrist_interaction.diagnostics` flag additionally logs every processed
  frame's session, frame index, source time, track IDs, pose count, candidate
  scores/geometry/rejections, wrist confidences and inference latency. The flag
  remains false by default; the validation listener separately recorded all frames.
- Missing/failed/skipped pose samples are explicitly classified, without reusing
  cached landmarks as new evidence. Existing source-time sampling, one model per
  worker, restart isolation, pause behavior and cleanup remain in place.

Confidence thresholds were **not lowered**: visibility and presence still must
both reach 0.5, with finite in-frame wrist coordinates. Other activity-event
semantics, authentication, timers and production alert rules were not changed.

## Measured Lite / Full comparison

Both official models processed the same 144 source frames, with identical stored
ByteTrack boxes and identical thresholds. In a paired CPU comparison, model order
alternated each frame to reduce order/load bias. First-five-frame timings were
excluded from the inference means below. The original matcher was preserved as
a temporary baseline and evaluated against the same model outputs.

| Configuration | Accepted pose matches | Reliable wrist observations | Unmatched track observations | Interaction event time |
| --- | ---: | ---: | ---: | --- |
| Original Lite + original matcher | 173 | 133 | 91 | 7.083 s |
| Lite + revised matcher / 0.5 s tolerance | 175 | 135 | 89 | 12.500 s |
| Full + original matcher | 164 | 125 | 100 | 5.208 s |
| Full + revised matcher / 0.5 s tolerance | 175 | 146 | 89 | 5.208 s |

Both models returned 177 poses on 133 of 144 frames. Full did **not** improve
raw pose detection coverage. Refined matching recovered two additional Lite
matches; Full supplied 11 more reliable wrist observations than refined Lite
(8.1%), and 13 more than the original baseline (9.8%). Match acceptance rose from
173/177 (97.7%) to 175/177 (98.9%); this is acceptance coverage, not identity accuracy.
There is no manually labeled pose-to-track ground truth to claim a formal accuracy.

The stricter 0.5-second dropout bound delayed the Lite event in this recording;
that regression is not hidden. Full supplied reliable observations through the
earlier handle interaction without changing the threshold. Its event-time frame
was inspected: the operating person's right wrist is inside the cabinet ROI,
visibility approximately 0.87 and presence 0.99. Lite's same-frame wrist visibility
was approximately 0.48 and was correctly rejected under the unchanged 0.5 threshold.
No event is described as confirmed opening or object pickup.

Paired CPU inference means: Lite **54.59 ms**, Full **66.32 ms** (+21.5%);
medians 52.26 / 62.50 ms. On 88 common valid consecutive wrist pairs, median
normalized frame displacement was 0.00515 for Lite and 0.00277 for Full (means
0.01782 / 0.01627). Displacement includes real hand motion and is only a stability
proxy, not a ground-truth localization-error measure.

Based on the observed wrist quality, inspected handle interaction and roughly
12 ms additional pose CPU cost, **uploaded replay now explicitly selects Full**.
Live/interactive pose preview keeps Lite. This was a measured choice, not an
automatic fallback or global model replacement. Persistent single-pose gaps
remain; this change does not claim to eliminate occlusion.

The Full model is installed locally at `app/models/pose_landmarker_full.task`
(ignored binary asset), SHA-256
`5134A3AAD27A58B93DA0088D431F366DA362B44E3CCFBE3462B3827A839011B1`.
Other checkouts can install/verify it with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/download_pose_landmarker_model.ps1 -Model full
```

The existing downloader defaults to Lite and now supports the pinned official
Full artifact. `wrist_interaction.pose_model_path` controls the replay choice;
setting it to null uses the existing preview model configuration. The existing
`VAULT_POSE_LANDMARKER_MODEL` environment override still takes precedence.

## Complete real replay and checks

Recording: `temp/vault_authorized_employee_operation_30s_smooth.mp4`, 1280 x 720,
24 FPS, 30 seconds. SHA-256:
`96162fc1ac51bd11c1dc66649058ec6d89b13b2492e6815cff07e5445bec624b`.
Completed Full replay: `08fa0197df824b509a512bb657f162dc`.

- All 144 sampled frames completed. Actual Full pose inference averaged 58.85 ms.
  End-to-end wall time was about 138 seconds including model startup, pause,
  browser requests and concurrent tests, so it is not a controlled pipeline-speed
  comparison with earlier runs.
- Two people remained confirmed. PERSON_DETECTED x3 tracking episodes,
  PERSON_ENTERED x1 and SESSION_STARTED x1 (source time 1.25 seconds) were preserved.
  Body-position VAULT_AREA_ENTERED remained zero under unchanged saved geometry.
- VAULT_AREA_INTERACTION occurred once, at **5.208333 seconds**, Track 1/right
  wrist, six valid observations over 1.25 seconds, simulated authorization true.
  All six activity evidence JPEGs were retrieved and the actual debug/evidence
  frame was inspected. No visibly spurious interaction was found in the single
  reviewed episode; a general false-positive rate cannot be established without
  labeled ground truth. No replay alerts occurred.
- Observed per-track statuses: OBSERVED 136, UNRELIABLE 39, TEMPORARILY_MISSING 19,
  LOST 52, UNMATCHED 18. All 89 unmatched track observations were classified as
  no compatible returned pose, rather than fabricated association successes.
- All five frame-snapshot polygons matched the saved profile exactly. Browser
  checks passed for clean/debug switching, fullscreen, event/evidence updates,
  transient preview failure, pause/resume and source-time freezing.
- The idle main backend was reloaded with its environment preserved. All six
  durable events and evidence were retrieved afterward on port 8010. Saved profile
  data remained unchanged, with zero production authorization/alert rows for replay.
- **81 backend tests passed**, covering torso/arm geometry, pose-order changes,
  ambiguity with history, dropout cache expiry, missing samples never emitting,
  immutable frame diagnostics, existing replay isolation/evidence/door guards,
  profile persistence, counting, authorization and alert rules.

## Exact files changed

Relative to `backend/use_cases/vault_monitoring`:

- `app/core/ml_config.py`
- `app/services/pose_preview.py`
- `app/services/vault_wrist_interaction.py`
- `app/services/vault_room_manager.py`
- `app/services/vault_room_replay.py`
- `app/services/vault_pose_debug.py`
- `config/models.yaml`
- `scripts/download_pose_landmarker_model.ps1`
- `tests/test_vault_wrist_interaction.py`
- `tests/test_vault_activity.py` (pose fixture accepts model selection)
- `docs/vault-room-pose-stability.md`
- `app/models/pose_landmarker_full.task` (locally installed ignored model asset)

No frontend, RF-DETR, ByteTrack, saved-region, Entrance, Grill Gate or other use-case
implementation was modified. Start a new replay to use the updated worker.
