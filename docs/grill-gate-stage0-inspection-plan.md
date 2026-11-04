# Grill Gate Monitoring — Stage 0 Architecture Inspection and Plan

## Objective

Prepare a separate Grill Gate Monitoring use case for the Fedbank Vision Platform. The required capabilities are sliding gate open-duration monitoring, directional ENTRY/EXIT crossing events with a crossing-inactivity timer, and independent mesh-area gathering monitoring.

This document records the Stage 0 inspection and proposed plan. No detection or monitoring code was added as part of Stage 0.

## 1. Current architecture summary

The common registry already supplies stable locations, cameras, camera sources, use-case assignments, and assignment-scoped zones. A camera belongs to a location; its sources refer to server-side environment variables; assignments associate cameras with use cases. Assignment configuration and calibration are JSON fields, and zones also have a JSON calibration field. The additive registry migration creates these tables without replacing Branch Exterior’s legacy camera or zone tables.

Relevant files:

- `backend/use_cases/vault_monitoring/app/db/models/camera_registry.py`
- `backend/use_cases/vault_monitoring/migrations/20261103_common_camera_registry.sql`
- `backend/use_cases/vault_monitoring/app/services/camera_registry_service.py`
- `backend/use_cases/vault_monitoring/app/api/routes/regions.py`

The registry API is mounted under `/api/v1/regions`. It provides endpoints for use cases, locations, cameras, sources, assignments, and assignment zones. Writes use the configured caller authentication.

Grill Gate is registered as `grill_gate`, but its current zone configuration only lists `gate_approach`, `gate_trigger`, `gate_crossing`, and `gate_interior`. **`gate_leaf_roi` and `mesh_area` are missing.** The common zone API accepts normalized polygons; it does not currently represent a directional crossing line as a first-class geometry.

Relevant files:

- `backend/use_cases/vault_monitoring/config/use_cases/registry.yaml`
- `backend/use_cases/vault_monitoring/config/use_cases/grill-gate/zone_types.yaml`
- `backend/use_cases/vault_monitoring/app/schemas/camera_registry.py`

There is no Grill Gate detection, monitoring, event, or alert implementation in this checkout. Existing Grill Gate support is registry metadata only.

## 2. Existing frame and detection components

- `backend/shared/fedbank_core/camera_stream.py` provides an OpenCV capture-construction helper. It is not a shared camera worker or frame fan-out system.
- Branch Exterior has a camera-owned worker thread and a frame status bus. Detection, tracking, zone analysis, overlays, and alert dispatch run through its own pipeline. That pipeline contains Branch-specific business rules and should not be imported as Grill Gate behavior. See `backend/use_cases/branch_exterior/app/services/stream_worker.py`.
- Vault Room uses an RF-DETR person detector and ByteTrack tracker, with a capture queue that keeps the latest frame. Its detector, tracker, and zone manager are part of Vault Room’s own processing path and should remain unchanged. See `backend/use_cases/vault_monitoring/app/services/person_detector.py`, `person_tracker.py`, `vault_room_camera.py`, and `vault_room_manager.py`.

There is no existing single worker that safely delivers one camera’s frames to multiple independent use-case consumers. Separate capture loops for the gate, crossing, and mesh detectors could contend for the same CCTV source and repeat expensive inference.

## 3. Proposed Grill Gate module and frame-processing design

Add a separate Grill Gate module that consumes the common camera registry but owns its own monitoring state, configuration, and event flow. Do not change Branch Exterior or Vault Room business logic.

For an assigned Grill Gate camera, use one capture worker and a bounded latest-frame buffer. Run person detection and short-lived tracking once per processed frame, then pass immutable frame observations—with capture timestamp, sequence, dimensions, detections, and temporary track IDs—to three independent consumers:

1. Gate state estimation.
2. Person crossing detection.
3. Mesh-area gathering evaluation.

Each consumer should own its state and handle its errors independently. Use capture timestamps and monotonic elapsed time for timers. Drop stale frames rather than allowing processing queues to grow. Gate leaf analysis may also need the raw frame and a separate lightweight vision step.

This architecture supports independent rules while avoiding duplicate person inference. It also creates a clean boundary between shared source/frame infrastructure and Grill Gate-specific behavior.

## 4. Zones and calibration

All six requested zone types should be present in Grill Gate’s zone-type configuration:

- `gate_leaf_roi`
- `gate_approach`
- `gate_trigger`
- `gate_crossing`
- `gate_interior`
- `mesh_area`

These are editor metadata today, not active detector semantics. The common zone API supports polygons with `normalized_raw` coordinates; no polygon coordinates should be invented.

Keep person-monitoring ROIs as zones. Store gate-specific calibration separately on the camera assignment, using its existing calibration JSON field, with a versioned validation model. That calibration should define the directional crossing boundary, the mapping of its sides to ENTRY and EXIT, and gate-state reference/threshold data. Treat `gate_crossing` as a configured region or corridor; a polygon alone cannot reliably express the oriented boundary crossing needed to classify direction.

The current common editor can edit polygon zones, but it has no dedicated UI for line endpoints or physical gate-state calibration. A calibration UI will be needed before those values can be set and reviewed.

## 5. Gate state machine and separate timers

A Grill-specific state estimator should report `CLOSED`, `OPENING`, `OPEN`, `PARTIALLY_OPEN`, `CLOSING`, or `UNKNOWN`. It will need camera-specific references for the closed and fully open gate positions, confidence thresholds, temporal confirmation, and hysteresis. The side-angle view makes occlusion and apparent gate movement risks significant; person detections alone cannot establish the physical gate state.

Keep the two timers independent:

- **Continuous open-duration timer:** begins only after `OPEN` is confirmed and continues through intermediate movement states until `CLOSED` is confirmed. Crossing events never reset it. Once the configured maximum is exceeded, emit `GATE_OPEN_TOO_LONG` for that gate-open episode.
- **Crossing-inactivity timer:** begins when `OPEN` is confirmed and resets only on a valid `ENTRY` or `EXIT`. When its configured interval expires, emit its own inactivity event. It must not alter the open-duration timer.

Both timers need independent settings, state, and deduplication keys. Thresholds and confirmation durations belong in Grill Gate assignment configuration.

## 6. Crossing detection design

Use confirmed, temporary person tracks and their foot-point trajectory relative to a calibrated oriented boundary. Require a real side-to-side transition across that boundary, with direction mapped to ENTRY or EXIT. Add a small dead band, minimum displacement/temporal confirmation, and per-track crossing cooldown to reduce jitter and duplicate events. A person entering a nearby zone without crossing the boundary should not count.

Track IDs should be short-lived camera-local values, used only to connect observations across nearby frames. Do not store long-lived person identities. The existing Branch Exterior ByteTracker and Vault Room ByteTrack wrapper demonstrate available tracking patterns, but Grill Gate should own its tracking state and crossing rules.

## 7. Mesh monitoring design

Evaluate people currently inside `mesh_area` only. Start an aggregate presence timer when the configured minimum count is met; the provisional example is three people for 60 seconds. Produce `PEOPLE_GATHERING` at that threshold and a distinct `SUSPICIOUS_ACTIVITY` event if the gathering condition persists to the configurable five-minute threshold. Debounce brief count fluctuations.

This timer must use neither crossing events nor person identities. Normal public movement should not independently create an alert.

## 8. Events and alerts

The Branch Exterior event table and publisher are tied to its own domain schema and behavior. Do not reuse them for Grill Gate event generation. The central Alert Service has a generic producer contract, scoped by use case and producer, with idempotent creation and source-event updates. It can suit Grill Gate’s threshold alerts once Grill Gate producer credentials are configured.

Relevant files:

- `backend/services/alert_service/app/schemas/alert.py`
- `backend/services/alert_service/app/api/routes/alerts.py`
- `backend/services/alert_service/app/db/repositories.py`
- `backend/use_cases/branch_exterior/app/services/alert_publisher.py` (Branch-only integration; reference only)

The Alert Service is an **alert** lifecycle service, not a general crossing-event log. Recommended design: keep ENTRY, EXIT, state transitions, timer expirations, and camera interruptions in a Grill Gate domain event/outbox; publish only actionable threshold alerts to the Alert Service. Routine ENTRY/EXIT movement must not be a security alert.

One integration detail needs a decision in Stage 1: producer source-event updates can update source data, but alert resolution is a separate operator lifecycle action. Automatic gate closure should not be assumed to resolve an Alert Service alert without an explicit lifecycle design.

## 9. API and frontend integration plan

Use the existing common registry endpoints under `/api/v1/regions` for location, camera, source, assignment, and zone setup. Add Grill Gate runtime/configuration APIs for:

- Calibrating and reading gate state.
- Current direction-specific crossing events and crossing totals.
- Mesh count, duration, and alert condition state.
- Independent timer thresholds and active timer status.
- Camera/worker health and disconnection status.
- Grill Gate domain event history.

Add Regions & Zones UI support for all six zone types and a separate calibration workflow for the directional line and gate state. Add a Grill Gate monitoring view showing gate state, both independent timers, ENTRY/EXIT events, mesh count/duration, and camera health. Existing Alert Service listing can show Grill Gate alerts if operator credentials include the `grill_gate` scope.

## 10. Camera disconnect behavior

On camera disconnect, set gate state to `UNKNOWN`; do not keep accumulating open-duration or mesh-presence time without observations. Emit a distinct camera-health event. On reconnection, re-establish the gate state and restart crossing and mesh confirmation from fresh observations.

Because the physical gate may have closed while the camera was offline, the system cannot safely claim continuous open time across that blind interval. This policy avoids false duration alerts but may undercount an actual long opening. Keep this behavior explicit in the operator UI and event history.

## 11. Required tests

- Gate state transitions, confidence confirmation, hysteresis, occlusion, and restart behavior.
- Open timer continues across crossings and stops only at confirmed closure.
- Inactivity timer resets only on valid ENTRY/EXIT and raises independently.
- Directional crossing versus merely entering an ROI, including jitter, occlusion, and duplicate suppression.
- Independent mesh thresholds, durations, count-fluctuation debounce, and no coupling to crossings.
- Disconnection/reconnection timer handling and camera-health events.
- Alert idempotency, source-event version updates, and no security alert for routine crossings.
- Registry zone-type validation, calibration validation, and independent worker-consumer failure handling.
- Integration tests with representative side-angle footage and camera outage scenarios before enabling live monitoring.

## 12. Missing prerequisites and risks

1. **Camera calibration material:** representative side-angle footage and a captured reference frame are needed to calibrate physical gate states, the approach/interior sides, and the oriented crossing boundary. No calibration coordinates are included here.
2. **Timer policy:** the maximum open duration, inactivity interval, thresholds, confirmation times, and event severity need configuration defaults or operator-provided values.
3. **Outage semantics:** timer continuity across camera disconnection cannot be inferred. This plan proposes suspending timers, making state `UNKNOWN`, and requiring fresh confirmation after reconnection.
4. **Alert lifecycle:** the Alert Service treats operator lifecycle status separately from producer source status. Decide whether gate closure should resolve a corresponding alert automatically, or whether it only ends the domain event and leaves alert resolution to an operator.
5. **Crossing event storage:** the current Alert Service does not provide a routine event log. A Grill Gate domain event/outbox and read API are needed if ENTRY/EXIT events must be retained and displayed.
6. **Calibration UI:** current common zone editing handles polygons but not oriented crossing lines or gate-state calibration.
7. **Performance:** one detector/tracker pass can be shared among three Grill Gate consumers, but multiple cameras may compete for CPU/GPU, especially alongside Vault Room inference. Processing rate, model residency, and per-camera limits need measurement.
8. **Side-angle ambiguity:** occlusion, reflections, shadows, and gate/person overlap can make OPEN, PARTIALLY_OPEN, and UNKNOWN difficult to distinguish. A camera-specific calibration and staged validation are essential.

## 13. Suggested Stage 1 sequence

1. Agree on camera-outage timer behavior and alert-closure semantics.
2. Add the missing `gate_leaf_roi` and `mesh_area` types; define versioned assignment calibration validation without sample zones or invented coordinates.
3. Implement the Grill Gate module and one-camera frame worker with bounded buffering and independent consumer interfaces.
4. Implement and unit-test gate-state estimation and its two separate timers.
5. Implement and unit-test trajectory-based directional crossing.
6. Implement and unit-test independent mesh aggregation.
7. Add Grill Gate domain event persistence/outbox and publish only qualifying alerts through the configured Alert Service producer.
8. Add runtime/configuration APIs and Regions & Zones calibration plus monitoring UI.
9. Run integration tests with representative side-angle footage and camera outage scenarios before enabling live monitoring.

## Stage 0 status

Inspection and planning only. No code, database schemas, migrations, or frontend files were modified. Stage 1 should begin only after this plan is approved.
