# Vault Room operational activity events

Activity is independent of security alerts. No activity record creates an alert,
incident, or alert-evidence parent. RF-DETR, ByteTrack, the frame admission semaphore,
stable counter, camera workers, and uploaded-video decoder are reused unchanged.

## Rules and timing

- `PERSON_DETECTED`: each tracked person inside `person_monitoring_roi` must satisfy
  the confirmation duration and minimum frame count. It emits once per continuous
  tracked presence episode. A silently observed absence re-arms it; no exit event
  is emitted. Duplicate/non-increasing source timestamps cannot confirm presence.
- `PERSON_ENTERED`: exactly two unchanged track IDs in the person ROI and a stable
  count of two must persist for at least `max(1, zone.confirmation_seconds)` seconds.
  It emits once per monitoring session, with `person_count: 2`,
  `metadata.detection_method: "inferred_presence"`, and `verified_doorway_entry: false`.
- `VAULT_AREA_ENTERED`: each track in `vault_area_roi` must satisfy the zone's
  confirmation duration and minimum frame count. No duplicates while inside;
  silent absence permits a subsequent confirmed entry.
- `SESSION_STARTED`: for profiles with a person ROI, the existing room timer waits
  for confirmed two-person presence, two distinct authorized employee IDs, and the
  existing access grant/entry-buffer conditions. The existing configured session
  duration is used (360 seconds by default), with UTC `started_at`, `deadline`,
  duration and track IDs in metadata. Authentication and doorway rules are not
  replaced. Single-officer test grants cannot satisfy the activity start gate.

Uploaded frames use the decoder's frame-index/FPS timestamp, unaffected by inference
speed or pauses. Live events use elapsed monotonic processing time, with a separate
UTC creation timestamp. Tracks, pending confirmations and deduplication state belong
to each manager/replay. Grants reset temporal state for the new vault session.
Profiles without the person ROI keep their existing legacy timer behavior.

Membership uses the existing normalized reference geometry (bottom center by
default, honoring a zone's configured reference) with a normalized boundary tolerance.
Settings in the Vault environment:

| Setting | Default |
| --- | --- |
| `VAULT_ACTIVITY_CONFIRM_SECONDS` | 1.0 |
| `VAULT_ACTIVITY_MIN_FRAMES` | 2 |
| `VAULT_ACTIVITY_ROI_TOLERANCE` | 0.002 |

These do not change detector/tracker algorithms or security alert thresholds.

## Persistence and evidence

`ActivityEvent` is a separate validated domain model stored in the existing
`vault_room_events` audit table with `data.channel = "activity"`. Its JSON envelope
supports all activity fields, so no database migration is needed. Activity API
queries include that discriminator; legacy events/security audits are excluded.
Event UUIDs and primary-key admission make retried persistence idempotent.

Writes use the existing asynchronous room writer. Evidence reuses JPEG capture,
the existing `validate_image` validator and `EVIDENCE_SPOOL_DIR` convention. Activity
snapshots live in a durable `activity/` subdirectory, keyed by SHA-256. Events
confirmed on the same frame share a snapshot. Access requires the Vault API key;
checksum validation guards retrieval. Activity evidence is intentionally independent
of temporary replay deletion and alert retention/incident lifecycle.

Each persisted batch has an atomic JSON outbox file until its DB transaction
commits. Startup retries pending batches; existing event IDs suppress duplicates.
The evidence spool must reside on durable storage and be backed up with the DB.
Committed history remains available after service restart and replay cleanup.

## API contract

All endpoints require the existing `X-API-Key` when `VAULT_ROOM_API_KEY` is configured.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/v1/vault-room/activity-events` | Recent activity/history |
| GET | `/api/v1/vault-room/sessions/{session_id}/activity-events` | Session history, including replay UUIDs |
| GET | `/api/v1/vault-room/activity-events/{event_id}` | One activity record |
| GET | `/api/v1/vault-room/activity-events/{event_id}/evidence` | Authenticated JPEG evidence |

History returns `{ "items": [...], "total": n, "limit": 50, "offset": 0 }`, newest
first. Pagination: `limit` 1–200 and nonnegative `offset`. Filters: `event_type`,
`source_id`, `camera_id`, `source` (`webcam`, `cctv`, `upload`), `replay`, `since`,
`until`; recent history also accepts `session_id`. Time filters use ISO UTC/offset
creation timestamps and inclusive bounds; naive/reversed ranges return 422.

Each item includes `id`, `type`, `session_id`, `camera_id`, `source_id`,
`video_timestamp_seconds`, `created_at`, `track_ids`, `person_count`, `zone_id`,
`description`, `evidence_reference`, `source`, `replay`, `test_mode`, and `metadata`.
When `evidence_reference` is non-null, use the evidence endpoint above. Source IDs
identify the selected profile (or explicit capture ID); uploaded source/session IDs
are the replay UUID. Camera ID prefers existing registry identity when available.

For live updates, the existing `/api/v1/vault-room/events` SSE emits a `vault_event`
whose JSON has `type: "activity.created"` and `data` containing the committed
activity model. Replay records carry `replay: true`; consumers must filter as
appropriate. Replay activities are published into their replay session's event ring
and are available through the existing video-status and activity-history polling
APIs; they do not enter the production room's SSE ring. Paginated polling is also supported. After an SSE reconnect, backfill
history via `since` (inclusive) and deduplicate by event ID.

### Explicit replay authorization

The existing `POST /api/v1/vault-room/video-sessions/{id}/start` accepts:

```json
{"required_persons": 2, "profile_id": "upload", "simulated_authorization": true}
```

`simulated_authorization` defaults to **false**. It is applied only to the isolated
replay manager's activity authorization gate. It cannot authenticate real employees,
unlock production access, or modify the live manager. Activity still requires real
tracked two-person confirmation. Metadata identifies the simulated authorization.
Existing replay security alerts retain their separate test-only behavior.
Explicit simulation also supplies the isolated replay alert engine's verified count;
its session timer begins on confirmed authorized presence and uses video time.

Restart the Vault backend to load the new activity routes and worker integration.

## Validation

The focused backend regression run covers activity rules/APIs, profile persistence,
decoded uploaded-video replay, room rules/manager/counting/cameras/routes, security
alert rules/persistence, zone providers and Grill Gate registry compatibility.
83 tests passed. Camera reconnect delay was set to 0.1 seconds for the existing
unavailable-webcam test's two-second deadline; production retry settings were not
changed. Decode/tracker integration uses generated video and a deterministic
detector fixture; it does not certify RF-DETR accuracy on a particular recording.
The original Vault recording must be provided separately for that recording-specific
acceptance run. Live PostgreSQL read endpoints were also checked (200, 401 and 422)
without inserting synthetic production activities.
