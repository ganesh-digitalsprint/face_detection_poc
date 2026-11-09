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

`gate_open_enabled` and `max_gate_open_seconds` configure `GATE_OPEN_WITHOUT_CROSSING`. Its timer accumulates only while the gate reports `OPEN`; `UNKNOWN`, `OPENING`, and `CLOSING` pause it. A confirmed ENTRY or EXIT resets the timer; a confirmed `CLOSED` state resets the gate episode. An active crossing or unreliable crossing reading suppresses alert creation without resetting the timer. Once conditions become reliable and clear, an elapsed timer raises one alert for that interval.

When crossing state is temporarily unreliable, the rule does not claim that crossing activity is absent. `crossing_unknown_recovery_frames` configures how many consecutive valid detector updates are needed to trust crossing state again after a transient interruption. If an in-flight track is lost past the tracker stale timeout, crossing state stays unknown until the detector session is reset/reconfigured; this deliberately favors suppression over an alert based on missing data.

Grill Gate alert conditions are stored locally and listed through the assignment-scoped `/api/v1/grill-gate/assignments/{assignment_id}/alerts/active` endpoint. Optional shared Alert Service fan-out uses the configured producer and operator credentials, but local generation and retrieval work independently of that service.

Unauthorized crossing alerts remain unimplemented because there is no reliable authorization result linked to a tracked crossing. Camera-availability alerts remain unimplemented because the camera worker currently exposes status snapshots but no reliable disconnect/reconnect event contract.
# Uploaded video jobs

The host application exposes authenticated backend endpoints under `/api/v1/grill-gate/videos`.
Uploads require either `template_assignment_id` (an active Grill Gate assignment copied as a
configuration snapshot) or a JSON `configuration` form field containing `calibration`, `zones`
and optionally `zone` and `alert_configuration`. Jobs decode MP4/AVI frames sequentially and pass
them through the same gate detector and frame processor used for live camera frames. Each job has
its own tracker, crossing/mesh state and alert rule engine. A template is read-only; no camera
worker is connected or changed.

An upload saves the video as an `UPLOADED` job; zones and calibration are optional at that point and
are set on the job afterwards. Processing begins when `POST .../start` is called and the job is ready. Each
run can be started once. Starting locks its configuration, so later edits cannot change a running or
finished run. `POST .../reprocess` creates a fresh run with independent detector/tracker state and event rows
over the original retained video asset. Deleting any job in an asset group removes the uploaded asset and
all inactive processing runs, their video-specific events and local alert records. Each run keeps its own
immutable `config_snapshot` until that asset group is explicitly deleted.

Named zone configurations are stored separately from video results and scoped to the authenticated operator
identity. Jobs copy the selected configuration into their own snapshot, so later edits or deletion of a saved
configuration do not change historical processing results.

Endpoints:

- `POST /api/v1/grill-gate/videos` — multipart upload; saves an `UPLOADED` job without processing it.
  `template_assignment_id` or `configuration` are optional.
- `POST /api/v1/grill-gate/videos/{job_id}/start` — start a saved job (`409` if not `UPLOADED` or not
  ready, listing what is missing; `429` if the queue is full).
- `GET`/`PUT /api/v1/grill-gate/videos/{job_id}/config` — the job's zones, tuning, calibration and alert
  rules. A calibration must match the video's decoded frame size. `PUT` returns `409` after start.
- `POST /api/v1/grill-gate/videos/{job_id}/config/copy` — copy from `source_job_id` or
  `source_assignment_id`, only when frame sizes match.
- `GET /api/v1/grill-gate/videos/{job_id}/frame?t=&max_width=` — downscaled JPEG at a video time.
- `POST /api/v1/grill-gate/videos/{job_id}/measure-endpoints` — `closed_t` and `open_t`; returns the four
  endpoint fractions without saving them.
- `GET /api/v1/grill-gate/videos/{job_id}/preview?t=&max_width=` — JPEG from the processed part of the
  video only; the newest processed frame when `t` is omitted (`409` before any frame is processed).
- `GET /api/v1/grill-gate/assignments/{assignment_id}/preview` — the live camera's latest fresh frame as a JPEG
  (`409` when there is none).
- `DELETE /api/v1/grill-gate/videos/{job_id}` — remove a job that is not running, with its events and video.
- `GET /api/v1/grill-gate/videos` — list jobs (`status`, `limit`, `offset`).
- `GET /api/v1/grill-gate/videos/{job_id}` — status and progress.
- `POST /api/v1/grill-gate/videos/{job_id}/cancel` — request cancellation; a job that was never
  started becomes `CANCELLED` immediately. Its video stays until Delete.
- `GET /api/v1/grill-gate/videos/{job_id}/results` — persisted crossing/mesh events and
  matching shared Alert Service alerts.

`POST /api/v1/grill-gate/videos/{job_id}/reprocess` creates a fresh run over the retained asset; an optional
`zone_configuration_id` selects another saved configuration. Named configurations are available through
`GET`/`POST /api/v1/grill-gate/zone-configurations`, `GET`/`PUT`/`DELETE /api/v1/grill-gate/zone-configurations/{id}`,
and `POST /api/v1/grill-gate/zone-configurations/{id}/duplicate`.

The runner defaults to one concurrent decode/inference job and three queued jobs. Set
`GRILL_GATE_VIDEO_MAX_CONCURRENT`, `GRILL_GATE_VIDEO_MAX_QUEUED`,
`GRILL_GATE_VIDEO_UPLOAD_DIR` and `MAX_VIDEO_UPLOAD_MB` in the host environment to tune it.
Interrupted jobs are marked `FAILED` with `PROCESS_INTERRUPTED` during startup recovery.

Results also include `transitions`, the job's gate-state changes with video times. Live gate-state status
keeps its recent transitions in memory only, so they are lost when the server restarts.

Apply `migrations/20261107_grill_gate_video_jobs.sql` with the existing manual SQL migration
workflow before running against a database that already has `grill_gate_events`. The paired
`_down.sql` file reverses the schema changes; downgrade requires video event rows to be removed
first because the previous schema requires camera and assignment IDs.

The `20261109_grill_gate_reuse.sql` migration adds reusable named configurations and links independent
processing runs to the original retained video asset. Its paired `_down.sql` file reverses these additions.
