# Frontend Open Without Crossing timer changes

The frontend owns the cycle start, elapsed duration, threshold decision, and request lifecycle. Production frame processors use frontend-owned threshold evaluation; the backend retains monitoring evidence for validation and persists incidents.

## Shared video timebase for both cards

Gate Open previously started a component-local `Date.now()` stopwatch with a one-second interval, while Open Without Crossing used the persisted processed-video timestamp. The video view model also still projected its Gate Open duration using wall time. This caused different rates of advancement during slow video processing.

Both uploaded-video cards now use the same normalized `videoTimestampSeconds` from the existing Redux session. The active calculations are:

```javascript
const processedMs = videoTimestampSeconds * 1000;
const gateOpenSeconds = Math.max(0, (processedMs - gateOpenedAt) / 1000);
const openWithoutCrossingSeconds = Math.max(0, (processedMs - cycleStartedAt) / 1000);
```

`gateOpenedAt` records the frontend-confirmed FULLY_OPEN transition. ENTRY/EXIT leaves that timestamp intact and resets only `cycleStartedAt`. At footage timestamps open=10s, crossing=25s, current=30s, the cards show 20s and 5s. Neither duration advances between processed samples.

The video Gate Open card is display-only and has no interval. The projected clock was removed from the video hook/model/page path. Its support text uses the same `Video time` label as Open Without Crossing. The live Gate Open card retains its existing wall-clock implementation, and live Open Without Crossing is unchanged.

On a confirmed transition out of FULLY_OPEN, Redux stores `videoGateOpenStoppedSeconds` at the transition's video timestamp before clearing the active start. This preserves the Gate Open result while Open Without Crossing stops. A new confirmed open starts a new episode. Both durations freeze at terminal video status, remain available across persistence/navigation, and reject stale video observations or new cycles after completion. Missing timestamps retain the last stored processed sample; without a valid sample/start, Gate Open shows unavailable. Existing stored state that lacks a completed episode's start/stop evidence cannot reconstruct that historical duration.

No alert-controller, runtime, backend, API-contract, detection, tracking, or crossing-classification changes were made in this synchronization update. Existing threshold, final-frame evaluation, retry, and deduplication tests remain passing.

Exact files changed for synchronization:

- `frontend/src/use-cases/grill-gate/components/GateOpenCard.jsx`
- `frontend/src/use-cases/grill-gate/components/MonitoringPanels.jsx`
- `frontend/src/store/slices/gateMonitoringSlice.js`
- `frontend/src/store/index.js`
- `frontend/src/use-cases/grill-gate/hooks/useVideoJob.js`
- `frontend/src/use-cases/grill-gate/videoJobModel.js`
- `frontend/src/use-cases/grill-gate/pages/GrillGatePage.jsx`
- `frontend/src/use-cases/grill-gate/videoTimerClock.test.js`
- `docs/grill-gate-frontend-timer.md`

Validation: `npm.cmd test` passed all 160 tests. The production build passed with the existing bundle-size warning; output was written to `tmp/grill-gate-shared-clock-build`. `git diff --check` passed. Tests cover the 20s/5s example, shared-clock frame jumps, CPU/poll delays, independent ENTRY/EXIT behavior, confirmed stop/reopen transitions, terminal freezing, persistence/navigation, invalid samples, stale responses, live wall-clock values, and unchanged alert threshold/deduplication behavior. No interactive browser or real-camera smoke test was performed. Values update on processed-sample arrival; slower processing and polling can still make video time advance more slowly than real time.

## Footage-time correction

The uploaded-video timer intentionally measures footage duration, not CPU processing time. A slow-looking timer reflects processed-video timestamps arriving through the existing 2-second poll loop, with network/processing latency between updates. No runtime profile was taken to attribute additional delay to a blocked browser thread. A 20-second processing delay does not add 20 seconds to the footage timer. Poll frequency and live wall-clock monitoring remain unchanged in this follow-up.

The processed timestamp arrives as `results.monitoring.video_timestamp` (seconds), with matching job monitoring/status fields used when available. `videoTimerClock.js` normalizes it without extrapolation. Only an explicit zero-based source `frame_index` plus valid source `job.fps` can substitute for a missing time; processing FPS/frame counts cannot. An explicitly missing/invalid processed timestamp does not fall through to decoder progress.

Redux stores `cycleStartedAt` in milliseconds in the `video` timebase. The new `videoTimestampSeconds` stores the latest valid processed sample, and `videoProcessingStatus` freezes it on COMPLETED/FAILED/CANCELLED. The existing cycle remains the sole timer reference:

```javascript
elapsedVideoSeconds = Math.max(0, (videoTimestampSeconds * 1000 - cycleStartedAt) / 1000);
```

Cycle resets still require an ENTRY/EXIT count increase. The latest applicable crossing-event video timestamp is preferred over the later polling timestamp; unchanged/decreased counts and new-session baselines do not reset the cycle. The final frame is evaluated during an already-observed active run before freezing, including a crossing cycle first discovered in that response. Reopened completed jobs cannot create a new request merely from their final duration.

The card now prefixes support text with `Video time`. Last-crossing age uses the same processed sample, and missing crossing evidence shows `No crossing since gate opened`. Backend Open Without Crossing values and projected Gate Open display time cannot start this timer. Live wall-clock calculations remain unchanged; the shared-clock synchronization above now also applies footage time to Gate Open.

At a threshold jump from 3.5 to 5.2 seconds the shared frontend controller sends `elapsed_seconds: 5.2` immediately on that observed sample. It retains the existing `evaluate-open-gate` endpoint, retry payload/key, persisted confirmation, and Active Alerts refresh. No backend/API contract changes were made in this follow-up. The earlier request/response examples below still apply; a cycle starting at video 10.0 with a sample at 15.2 sends `timer_cycle_id: "video:footage:10000"` and `video_timestamp_seconds: 15.2`.

Exact files changed in this follow-up:

- `frontend/src/store/index.js`
- `frontend/src/store/slices/gateMonitoringSlice.js`
- `frontend/src/use-cases/grill-gate/components/OpenWithoutCrossingCard.jsx`
- `frontend/src/use-cases/grill-gate/hooks/useVideoJob.js`
- `frontend/src/use-cases/grill-gate/pages/GrillGatePage.jsx`
- `frontend/src/use-cases/grill-gate/videoJobModel.js`
- `frontend/src/use-cases/grill-gate/videoJobPoller.test.js`
- `frontend/src/use-cases/grill-gate/videoTimerClock.js` (new)
- `frontend/src/use-cases/grill-gate/videoTimerClock.test.js` (new)
- `docs/grill-gate-frontend-timer.md`

Follow-up validation: 154 frontend tests passed; the production build passed; 7 focused backend tests passed (70 deselected); `git diff --check` passed. New coverage exercises slow processing, skipped frames, delayed polls, ENTRY/EXIT event-time resets, closed/partial states, final timestamp loss, all terminal statuses, session navigation/persistence, threshold jumps and captured payloads, completed-job deduplication, invalid timestamps/FPS, and unchanged live wall-clock elapsed values. API invocation is verified with the controller test double; persistence, alert readback, and idempotency are verified through FastAPI tests with a test database. No interactive browser or real-camera smoke test was performed.

## Root cause

The checked-out card owned a component-local wall-clock interval and local request refs for both sources. It did not use the existing processed-video timer, lost request state on unmount, and displayed success from monitoring snapshots rather than shared API confirmation. The existing callbacks reached valid API endpoints, but the video endpoint rejected requests after processing completed and required a running detector. Publisher queue acceptance also did not prove local incident persistence. These paths allowed the UI to report threshold reached without a confirmed incident.

The attached task described an `isVideo` early return; that branch was absent in the checked-out version. The fix addresses the implementation found in this workspace.

## Flow and lifecycle

1. Existing Redux classification and count reducers maintain confirmed FULLY_OPEN cycle starts. Other states stop counting; increases in ENTRY/EXIT reset the cycle. Baseline initialization and decreases do not count as crossings.
2. Redux preserves each live assignment/video job session and its request records. Persistence includes cycle timestamps and count baselines.
3. Live elapsed uses the frontend wall-clock cycle start. Uploaded-video elapsed uses the processed video timestamp only. Uploaded-video Gate Open uses the same processed timestamp with its independent open-episode start.
4. The shared controller sends the existing API request at the first qualifying frontend update, using the configured threshold and actual elapsed value. Video polling invokes it independently of the card; live threshold deadlines survive page unmounts within the running application.
5. The card displays COUNTING, THRESHOLD REACHED, ALERT REQUEST PENDING, ALERT RAISED, ALERT REQUEST FAILED, FINAL, and NOT COUNTING from the cycle/request lifecycle. Success requires backend confirmation of a persisted row. Successful page-level evaluations refresh the existing alert reads.
6. Active video polling continues across route/source changes while the application remains open. Background updates remain scoped to their original job. Completed video duration stays on its final processed timestamp. EOF preserves the last processed observation for validation.
7. A cycle observed active can qualify on the final frame. Reopening a completed video without an observed active cycle does not initiate a new request merely because its stored duration exceeds the threshold.
8. Failed requests retry with exponential backoff capped at 30 seconds and the same captured payload/key. Captured requests can reconcile against stored transition/crossing evidence after completion, including a cycle whose gate subsequently closed.

## Existing endpoints used

- `POST /api/v1/grill-gate/assignments/{assignment_id}/alerts/evaluate-open-gate`
- `POST /api/v1/grill-gate/videos/{job_id}/alerts/evaluate-open-gate`

The existing authenticated Axios client is reused. No duplicate endpoint was introduced.

Illustrative video request (replace the job identifier with the selected job):

```json
{
  "elapsed_seconds": 4,
  "threshold_seconds": 4,
  "timer_cycle_id": "video:job-id:8500",
  "gate_session_id": "video:job-id",
  "gate_state": "FULLY_OPEN",
  "entry_count": 0,
  "exit_count": 0,
  "video_timestamp_seconds": 12.5
}
```

Confirmed response fields (active evaluation also returns monitoring fields):

```json
{
  "alert_evaluated": true,
  "alert_raised": true,
  "timer_cycle_id": "video:job-id:8500",
  "alert_id": "persisted-alert-id"
}
```

Live requests use the assignment endpoint and a `live:{assignment_id}:{cycleStartedAt}` key; video time is omitted. The source identifiers are scoped by the endpoint. The backend validates the configured enabled rule, threshold, gate state, finite elapsed value, and authoritative duration bound. Final reconciliation additionally validates session/job identity, recorded video timestamp, and supplied crossing counts against stored events. Historical validation uses the retained transition history.

## Duplicate prevention

The shared controller permits one in-flight request per cycle. Redux persists confirmation across remounts and refreshes. Every retry reuses its payload and cycle ID. The backend derives a stable UUID from assignment/camera/cycle identity; the existing unique `source_event_id` constraint and persistence conflict handling suppress duplicate incidents, including concurrent retries. New crossing cycles have different keys.

## Files changed for this task

Frontend:

- `frontend/src/store/index.js`
- `frontend/src/store/slices/gateMonitoringSlice.js`
- `frontend/src/store/slices/gateMonitoringSlice.test.js`
- `frontend/src/use-cases/grill-gate/api/grillGate.js`
- `frontend/src/use-cases/grill-gate/components/OpenWithoutCrossingCard.jsx`
- `frontend/src/use-cases/grill-gate/components/MonitoringPanels.jsx`
- `frontend/src/use-cases/grill-gate/components/LiveCameraSection.jsx`
- `frontend/src/use-cases/grill-gate/components/UploadedVideoSection.jsx`
- `frontend/src/use-cases/grill-gate/hooks/useVideoJob.js`
- `frontend/src/use-cases/grill-gate/pages/GrillGatePage.jsx`
- `frontend/src/use-cases/grill-gate/videoJobModel.js`
- `frontend/src/use-cases/grill-gate/videoJobPoller.test.js`
- `frontend/src/use-cases/grill-gate/openTimerController.js` (new)
- `frontend/src/use-cases/grill-gate/openTimerRuntime.js` (new)
- `frontend/src/use-cases/grill-gate/openTimerController.test.js` (new)

Backend under `backend/use_cases/grill_gate_monitoring/`:

- `api/grill_gate.py`
- `services/alert_rule_engine.py`
- `services/frame_processor.py`
- `services/gate_state_detector.py`
- `services/gate_state_detector_manager.py`
- `services/video_jobs.py`
- `tests/test_frontend_open_timer.py` (new)
- `tests/test_video_job_api.py`

Existing staged and unstaged work was preserved; this list describes the task edits, not all repository modifications.

## Original implementation verification

- Frontend: `npm.cmd test`: 137 tests passed.
- Frontend: `npm.cmd run build`: passed; Vite reports a large bundle warning.
- Focused backend: frontend rule tests plus API tests selected with `-k "frontend or timer or monitoring_summary"`: 7 passed, 70 deselected.
- Broader backend run before the last historical-request test: 86 passed, 6 failed. Failures: UNKNOWN pause expectation; named configuration polygon indexing; expected corridor zone at start; expected OPEN in the worker-flush fixture; obsolete `_crossing` attribute expectation; exact configuration equality after defaults expansion. These failures were not repaired by changing classification, crossing, or configuration behavior outside this task.
- `git diff --check`: passed.

No real-camera or interactive browser smoke test was performed. Closing the browser stops frontend execution; immediate alerts cannot be sent while it is closed. Persisted captured requests and the retained backend evidence support reconciliation after the frontend resumes; this is not a browser-independent frontend worker. Historical reconciliation is bounded by retained backend transition/event evidence.
