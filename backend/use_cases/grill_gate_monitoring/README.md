# Grill Gate alert rules

Alert rules are stored in the shared camera assignment's `configuration.grill_gate_alerts` object and are loaded by the live detector. Rules default to disabled and thresholds default to unset. Example:

```json
{
  "grill_gate_alerts": {
    "gate_open_enabled": true,
    "max_gate_open_seconds": 120,
    "gate_open_severity": "WARNING",
    "crossing_unknown_recovery_frames": 2,
    "partially_open_enabled": true,
    "max_partially_open_seconds": 60,
    "partially_open_severity": "HIGH",
    "mesh_occupancy_enabled": true,
    "max_mesh_occupancy": 4,
    "mesh_occupancy_severity": "WARNING"
  }
}
```

Unset or disabled thresholds do not raise alerts. `max_mesh_occupancy` means the maximum allowed count; an alert starts only when occupancy is greater than that value.

For `GATE_OPEN_TOO_LONG`, Stage 2 considers a track active after it has an observed endpoint origin (`gate_approach` or `gate_interior`) and then enters `gate_trigger` or `gate_crossing`. It leaves that active state after a confirmed destination crossing or a reversal to its origin. An unconfirmed direct jump between endpoints is treated as unreliable, not as proof that the crossing ended. All active tracks are counted, so one crossing finishing does not unblock the rule while another remains in progress. The gate-open timer is independent; it accumulates only while the gate reports `OPEN`, pauses during transitional/unknown readings, and resets only on a `CLOSED` state.

When crossing state is temporarily unreliable, the rule does not claim that crossing activity is absent and resolves any open-too-long alert while status is unknown. `crossing_unknown_recovery_frames` configures how many consecutive valid detector updates are needed to trust crossing state again after a transient interruption. If an in-flight track is lost past the tracker stale timeout, crossing state stays unknown until the detector session is reset/reconfigured; this deliberately favors suppression over an alert based on missing data.

The Vault Monitoring process publishes through the shared Alert Service using `ALERT_SERVICE_BASE_URL` and `ALERT_SERVICE_TOKEN`. Grill Gate alert query and lifecycle proxy routes also require `ALERT_SERVICE_OPERATOR_TOKEN`, configured in the Alert Service as an operator credential scoped to `grill_gate`. Delivery jobs are written to `GRILL_GATE_ALERT_OUTBOX_DIR` and retried asynchronously. The Alert Service remains the only alert record store.

Unauthorized crossing alerts remain unimplemented because there is no reliable authorization result linked to a tracked crossing. Camera-availability alerts remain unimplemented because the camera worker currently exposes status snapshots but no reliable disconnect/reconnect event contract.
# Uploaded video jobs

The host application exposes authenticated backend endpoints under `/api/v1/grill-gate/videos`.
Uploads require either `template_assignment_id` (an active Grill Gate assignment copied as a
configuration snapshot) or a JSON `configuration` form field containing `calibration`, `zones`
and optionally `zone` and `alert_configuration`. Jobs decode MP4/AVI frames sequentially and pass
them through the same gate detector and frame processor used for live camera frames. Each job has
its own tracker, crossing/mesh state and alert rule engine. A template is read-only; no camera
worker is connected or changed.

Endpoints:

- `POST /api/v1/grill-gate/videos` — multipart upload and queue a job.
- `GET /api/v1/grill-gate/videos` — list jobs (`status`, `limit`, `offset`).
- `GET /api/v1/grill-gate/videos/{job_id}` — status and progress.
- `POST /api/v1/grill-gate/videos/{job_id}/cancel` — request cancellation.
- `GET /api/v1/grill-gate/videos/{job_id}/results` — persisted crossing/mesh events and
  matching shared Alert Service alerts.

The runner defaults to one concurrent decode/inference job and three queued jobs. Set
`GRILL_GATE_VIDEO_MAX_CONCURRENT`, `GRILL_GATE_VIDEO_MAX_QUEUED`,
`GRILL_GATE_VIDEO_UPLOAD_DIR` and `MAX_VIDEO_UPLOAD_MB` in the host environment to tune it.
Interrupted jobs are marked `FAILED` with `PROCESS_INTERRUPTED` during startup recovery.

Apply `migrations/20261107_grill_gate_video_jobs.sql` with the existing manual SQL migration
workflow before running against a database that already has `grill_gate_events`. The paired
`_down.sql` file reverses the schema changes; downgrade requires video event rows to be removed
first because the previous schema requires camera and assignment IDs.
