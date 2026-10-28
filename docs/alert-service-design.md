# Common Alert Service Design (Pre-Stage 3B)

**Status:** Repository findings and design rationale. The finalized v1 wire contract is in [alert-service-contract.md](alert-service-contract.md); initial independent implementation is in `backend/services/alert_service/`. Vault and Branch remain unintegrated.

## 1. Scope and design boundary

The approved direction is one independently deployable Alert Service used by Vault Monitoring, Branch Exterior Monitoring, and future use cases. It should own a common alert record, cross-use-case listing, operator alert actions, lifecycle audit, and delivery of alert notifications. Use-case services remain independent producers/consumers and integrate through a versioned HTTP contract; they must not import one another's Python modules. This service is not an API gateway.

A common alert is an operational indication requiring triage. It is not automatically a Vault incident or a Branch event. Vault incident workflow, camera analytics, evidence capture policy, model thresholds, and Branch report/brief behavior remain domain-owned. The design keeps the source-domain object as a reference and allows domain metadata without making a common status enum erase domain-specific states.

## 2. Current-state findings (verified)

### Vault Monitoring

**Persistence and models**

- `backend/vault-monitoring/app/db/models/vault_room.py` maps `VaultRoomAlert` to PostgreSQL table `vault_room_alerts`. It stores ID, session reference, alert `type`, severity, message/title/source, count fields, camera/session references, first/last seen, occurrence count, timestamps, status, acknowledgement/resolution/dismissal actor and time, `incident_id`, JSON `metadata`, `dedup_key`, `row_version`, resolution note/source, and evidence status.
- That module also maps `VaultIncident` to `vault_incidents`, `VaultAuditEvent` to append-only `vault_audit_events`, `VaultIncidentComment` to `vault_incident_comments`, and `VaultEvidence` to `vault_evidence`. Evidence rows reference the current Vault alert and/or incident. Incident records support legal hold, row version, incident number, session and camera references.
- `backend/vault-monitoring/app/services/vault_alert_persistence.py` consumes worker jobs and persists rising/clearing episodes. It coalesces by `dedup_key`, increments `occurrence_count`, and can reopen a recently system-resolved row inside configured cooldown. On clear it system-resolves eligible open/acknowledged alerts. It also creates/updates incident associations and evidence-status changes. Queue overflow increments `dropped_transitions` and logs an error; a durable outbox is not shown in this path.
- `backend/vault-monitoring/app/services/vault_alert_rules.py` defines Vault-specific alert conditions/transitions. `backend/vault-monitoring/app/services/vault_event_publisher.py` forwards lifecycle messages into the Vault room manager event stream; it is not the proposed cross-service notification transport.
- `backend/vault-monitoring/app/db/vault_monitoring_repository.py` performs SQL persistence with caller-owned transactions, optimistic `row_version` checks, alert transition validation, incident creation/transitions, legal holds, comments, and `VaultAuditEvent` writes. Alert edges are `OPEN -> ACKNOWLEDGED | RESOLVED | DISMISSED`, then `ACKNOWLEDGED -> RESOLVED | DISMISSED`; terminal states have no outgoing transition. Incident edges are `OPEN -> INVESTIGATING | RESOLVED`, `INVESTIGATING -> RESOLVED`, `RESOLVED -> CLOSED`.
- `backend/vault-monitoring/migrations/20261026_vault_incidents_evidence_audit.sql` alters `vault_room_alerts` and creates `vault_incidents`, `vault_evidence`, `vault_incident_comments`, and `vault_audit_events`. `20261026_vault_alerts_stage3.sql` adds session references, deduplication/version/lifecycle fields and `vault_alert_conditions`, plus a PostgreSQL append-only audit trigger. These hand-managed migrations are not an Alert Service schema.

**HTTP and live behavior**

- `backend/vault-monitoring/app/api/routes/alerts.py`, prefix `/api/v1/alerts`, exposes:
  - `GET /api/v1/alerts` with scope, repeated `status`, severity, alert_type, camera_id, session_ref, incident_id, sort, from/to, cursor and limit filters.
  - `GET /api/v1/alerts/summary`, `GET /api/v1/alerts/meta`, and `GET /api/v1/alerts/{alert_id}`.
  - `POST /api/v1/alerts/{alert_id}/{acknowledge|resolve|dismiss}` with note and `expected_version`.
  - `POST /api/v1/alerts/{alert_id}/incident` to create/link a Vault incident.
  - Routes require `get_operator` and expose `allowed_actions`, row version, evidence summary, and Vault-specific metadata.
- `backend/vault-monitoring/app/api/routes/incidents.py`, prefix `/api/v1/incidents`, exposes incident detail, `PATCH /{incident_id}/status`, `POST /{incident_id}/hold`, and `POST /{incident_id}/comments`. Detail assembles alerts, evidence, comments, Vault session context, and audit timeline. These are incident workflows, not generic alert lifecycle endpoints.
- `frontend/src/api/alerts.js` calls Vault routes and normalizes alert rows; `frontend/src/hooks/useVaultAlerts.js`, `frontend/src/pages/VaultAlerts.jsx`, `frontend/src/components/alerts/VaultAlertsPanel.jsx`, and `frontend/src/pages/VaultIncident.jsx` consume them. The browser currently sends the POC `X-API-Key` from `VITE_VAULT_ROOM_API_KEY`; the source comments correctly note a bundled key is public.
- `frontend/src/api/vaultRoom.js` also consumes Vault room events using SSE. Alert lifecycle events emitted by `publish_alert_event` should not be conflated with the persistent list API.

### Branch Exterior Monitoring

**Persistence and model**

- `backend/branch-exterior-monitoring/app/models/orm.py` maps Branch `EventORM` to SQL table `events`. Fields include camera/zone IDs and names, scenario, severity, message, timestamps, status, track IDs, confidence, snapshot/clip paths, arbitrary `meta`, reviewer remarks, and dedupe key. The ID is a generated UUID4 string. The Mongo repository stores equivalent event documents in its `events` collection; Branch selects SQL-family or Mongo implementations behind repository interfaces.
- `backend/branch-exterior-monitoring/app/schemas/event.py` defines `EventCreate`, `EventReview`, `Event`, and `EventFilter`. Review labels are `confirmed`, `false_positive`, `under_review`, `closed`; the stored/default state is `open`. The review schema does not expose Vault acknowledgement/resolution semantics.
- `backend/branch-exterior-monitoring/app/db/repositories/interfaces.py` defines the async event repository contract, including `find_open_by_dedupe`, `touch`, `review`, and list/summary operations. Implementations are `app/db/repositories/sql_repo.py` and `mongo_repo.py`.
- `backend/branch-exterior-monitoring/app/services/alert_service.py` turns analytics `ScenarioSignal`s into persisted `Event`s, updates a matching open event within configured cooldown, merges maximum confidence/tracks/metadata, applies a new-event rate limit, captures evidence under Branch policy, calls `notify`, and broadcasts `{"type":"new_event","event":...}`. Branch `app/services/evidence_service.py` and storage policy decide snapshots/clips; this is not Vault's Cloudinary evidence store.

**HTTP and live behavior**

- `backend/branch-exterior-monitoring/app/api/routes/events.py` is mounted under `/api/events` and exposes `GET /api/events`, `GET /api/events/{event_id}`, `GET /api/events/{event_id}/report`, `POST /api/events/{event_id}/review`, `GET /api/events/export/csv`, and `DELETE /api/events` (all events or camera-filtered set). Detail/report/CSV contain Branch evidence paths, analytics metadata, track IDs, confidence and reviewer remarks.
- `app/api/routes/dashboard.py` derives counts/charts from Branch events. `app/api/routes/brief.py` derives the security brief from recent events. Neither is a generic alert API.
- `backend/branch-exterior-monitoring/app/ws/manager.py` holds an in-process WebSocket set and broadcasts best-effort. `app/api/routes/ws.py` serves `/api/ws/alerts`, sends a greeting, then receives messages to detect disconnects. `frontend/src/branch-exterior/feed.js` reconnects with backoff and emits only `new_event`; `frontend/src/branch-exterior/api.js` uses REST `/api/events` and WebSocket `/api/ws/alerts`. `AlertsDashboardPage.jsx`, `LiveMonitoringPage.jsx`, and `SecurityBriefPage.jsx` consume events.
- `backend/branch-exterior-monitoring/app/services/notification_service.py` logs events and optionally POSTs a webhook with a 5-second timeout. Delivery errors are logged and swallowed; the producer path does not persist retry records.

### Existing status conflict to preserve

Vault alerts are operational lifecycle records with `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `DISMISSED`. Linked Vault incidents have a separate investigation/closure lifecycle. Branch `events` are detector episodes with review outcomes (`under_review`, `confirmed`, `false_positive`, `closed`) and live event delivery. Treating these as one enum loses meaning. Separate common alert lifecycle from optional source-domain review state; retain Vault incidents as a separate aggregate.

## 3. Proposed canonical alert model (design decision)

Use a service-owned relational schema with these logical entities. Exact SQL names/types and migration tool remain an implementation decision; do not retrofit existing `events` or `vault_room_alerts` in place.

### `alerts`

| Field | Proposed meaning |
|---|---|
| `id` | Service-assigned immutable UUID, distinct from source ID. |
| `schema_version` | Producer envelope version. |
| `use_case`, `producer` | Stable, authorized producer namespace. |
| `source_event_id`, `source_event_type`, `source_event_version` | Original domain identity, kind and optional revision, preserved verbatim. |
| `source_uri` | Optional safe relative/API reference; never a credential-bearing URL. |
| `idempotency_key`, `deduplication_key` | Request retry identity and episode identity, kept distinct and scoped. |
| `category` | Extensible broad category such as security, access, camera, analytics or system. |
| `severity`, `source_severity` | Canonical `INFO`, `WARNING`, `HIGH`, `CRITICAL` plus original vocabulary when mapping is not lossless. |
| `title`, `summary` | Human-readable text without secrets or raw frames. |
| `occurred_at`, `first_seen_at`, `last_seen_at`, `received_at`, `updated_at` | UTC event, episode, ingestion and mutation times. |
| `status` | Common lifecycle `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `DISMISSED`; not source review state. |
| `acknowledged_at/by`, `resolved_at/by`, `dismissed_at/by` | Common lifecycle timestamps and scoped actors. |
| `resolution_note`, `resolution_source` | Outcome details and operator/system distinction. |
| `occurrence_count`, `row_version` | Episode count with defined semantics and optimistic concurrency version. |
| `resource_refs` | Namespaced identifiers for camera, zone, Vault session, Branch, etc. |
| `source_status` | Optional source-domain status, e.g. Branch review label. |
| `domain_data` | Versioned namespaced JSON retaining use-case-specific fields, e.g. Vault counts/session/incident link or Branch scenario/confidence/tracks. Validate size/depth and redact sensitive fields. |
| `evidence_refs` | Opaque IDs/provider references and availability summary only; no binary media or access URL. |

Enforce uniqueness on `(use_case, producer, source_event_id)` for a stable source record and on producer-scoped idempotency key. If producers reuse IDs for revisions, require source version/ETag rules. Episode deduplication is independent from request idempotency. Define exact occurrence merge semantics before implementation.

### `alert_audit` and notification records

- `alert_audit`: append-only mutation/ingestion history with alert ID, event/action, from/to status, actor type and scoped actor ID, timestamp, request/correlation ID, source reference, and redacted structured details. Restrict update/delete and govern audit retention.
- `notification_deliveries`: alert/event reference, destination/channel key (secret excluded), template/version, state, attempt count, next attempt, sanitized error class, timestamps, provider message ID, and delivery idempotency key. Store no webhook credential in payload/log.

A Vault incident remains a separate Vault-owned aggregate linked by a namespaced reference such as `vault_monitoring:incident:<id>`, unless incident ownership is explicitly changed later. Branch event review remains source-domain state until an adapter can preserve edits and reports.

## 4. Proposed API contract

Base path `/api/v1`; target port `8012` per approved architecture. Use JSON, UTC RFC3339 timestamps, stable errors, cursor pagination and explicit schema versioning. Require HTTPS/service authentication outside local development.

### Producer ingestion

`POST /api/v1/alerts` and optional bounded `POST /api/v1/alerts:batch` accept a versioned envelope:

```json
{
  "schema_version": "1.0",
  "use_case": "branch_exterior",
  "producer": "branch-exterior-monitoring",
  "source_event": {"id": "source-id", "type": "loitering", "version": 3, "uri": "/api/events/source-id"},
  "idempotency_key": "stable-producer-key",
  "deduplication_key": "episode-key",
  "occurred_at": "2026-10-28T12:00:00Z",
  "severity": "HIGH",
  "title": "Loitering detected",
  "summary": "...",
  "resource_refs": {"camera_id": "...", "zone_id": "..."},
  "source_status": "open",
  "domain_data": {"schema_version": "branch-event/1", "scenario": "loitering", "confidence": 0.91},
  "evidence_refs": [{"provider": "branch", "id": "..."}]
}
```

Caller identity, not body fields, authorizes `use_case`/`producer`. Return `201` for creation and `200` for identical replay with canonical ID, source reference, current status and `row_version`. Same idempotency key with different canonical payload returns `409 IDEMPOTENCY_CONFLICT`; invalid payload `422`; unauthorized producer `403`; retryable storage failure `503` plus request ID. Do not wait on notification delivery in ingestion.

An explicit occurrence/update operation such as `PATCH /api/v1/alerts/{id}/occurrence` may be added for stable episode sources; it must require producer identity/version and must not mutate operator lifecycle fields. Avoid ambiguous update-or-create semantics.

### Operator queries and detail

- `GET /api/v1/alerts`: filter by use_case, producer, status, severity, category, source type/ID, resources, incident reference, and time range. Stable cursor order on `(received_at,id)`, bounded page size, snapshot/ceiling and authorization scoping.
- `GET /api/v1/alerts/{id}`: canonical record, safe domain metadata, evidence references, allowed actions, source references and current `row_version`.
- `GET /api/v1/alerts/{id}/audit`: authorized audit history.
- `GET /api/v1/alerts/meta`: canonical enums, supported use cases/categories and compatibility capabilities, without unrestricted infrastructure disclosure.
- `GET /api/v1/alerts/summary`: same filters; adapters preserve current Vault summary fields.

### Lifecycle actions

Proposed endpoints:

- `POST /api/v1/alerts/{id}/acknowledgements` body `{ "note": "...", "expected_version": 4 }`.
- `POST /api/v1/alerts/{id}/resolution` body `{ "note": "...", "expected_version": 5, "outcome": "..." }`.
- `POST /api/v1/alerts/{id}/dismissal` body `{ "note": "...", "expected_version": 5 }`.

Each action and audit event commit atomically. Identical repeat returns current state; incompatible transition `409 INVALID_TRANSITION`; stale version `409 VERSION_CONFLICT`; missing item `404`; invalid/missing required note `422`. Preserve Vault's HIGH/CRITICAL dismissal rule in its adapter/policy until a common policy is approved. System resolution differs from operator resolution. These operations do not create or mutate a Vault incident.

### Notification delivery and live feed

Write a transactional outbox/notification job with ingestion or lifecycle mutation, then deliver asynchronously to configured channels. Internal/admin operations can inspect delivery status/retry; producer APIs cannot choose arbitrary destinations or payloads. A durable consolidated SSE/WebSocket feed may be added later with event IDs/cursors and reconnect replay. It is not needed to replace current transports in the first migration wave.

## 5. Stable integration contract

Publish a versioned wire contract (OpenAPI plus JSON Schema or equivalent generated artifacts). Producers use a typed HTTP client/DTO generated or implemented locally; they do not import another service's ORM or app modules. The shared package may contain DTO/schema only if compatible with both separate Python environments; otherwise generate language-local clients. Each request carries service identity, request/correlation ID, producer identity, source identity, idempotency key and schema version. Service URL and auth belong in each service's server-side settings. Specify payload limits, redaction, retention, timestamps, retries, mapping rules and compatibility guarantees.

## 6. Compatibility and migration strategy

### Vault

Keep `/api/v1/alerts`, `/api/v1/incidents`, and Vault room SSE as adapters during transition. Translate current filters, cursor, enums, item shape, summaries, metadata, action bodies, version conflicts and `allowed_actions`. `frontend/src/api/alerts.js` and current UI can remain unchanged for the first wave. Keep Vault alert types, `session_ref`, counts, evidence status, incident number, legal hold, comments and timeline available through namespaced metadata or Vault-owned incident endpoints. Continue routing incident create/detail/status/hold/comment operations to Vault unless incident ownership is separately decided.

Important referential issue: `vault_evidence.alert_id` references `vault_room_alerts.id`, and incidents/audit refer to Vault IDs. Do not change alert IDs in place. Preserve those IDs as compatibility/source identifiers or maintain a durable namespaced source-to-canonical mapping. During dual-write there must be one lifecycle authority; do not allow both stores to accept independent operator changes.

### Branch

Keep `/api/events`, reports, export, dashboard, brief and `/api/ws/alerts` intact in the first wave. An adapter may ingest a canonical alert after Branch `Event` commits, while `events` remains authoritative for analytics review, evidence paths, dashboards and reports. Do not map `confirmed`, `false_positive` or `under_review` to common `ACKNOWLEDGED`/`RESOLVED` without preserving source status. Keep `DELETE /api/events` restricted to Branch rows/media; it must not delete canonical records inadvertently.

Initially retain `{type:"new_event", event:<legacy Event>}` WebSocket payloads generated from `handle_signal`. Later project canonical updates into the same legacy envelope. When shifting webhook delivery, designate exactly one owner per destination to prevent duplicates.

### Ownership and backfill

**Proposal:** Alert Service owns its new schema only: canonical alert episodes, common lifecycle, audit, ingestion idempotency, notification outbox/attempts. Vault retains `vault_room_alerts`, incidents, evidence metadata/access/audit, comments, session references, and alert-rule episode state until an explicit reviewed cutover. Branch retains SQL/Mongo `events`, review state, reports/briefs, analytics state and filesystem evidence until reviewed cutover. Do not share or alter existing tables in this design.

Backfill/cutover sequence:

1. Inventory and snapshot source rows, IDs, statuses, timestamps, domain fields, attachment references and tombstones; confirm which Branch backend is in use.
2. Create a new service-owned schema separately, with forward migration and backup/restore rehearsal. Preserve namespaced source IDs; write mapping records and batch checksums.
3. Dry-run transform Vault alerts separately from Vault incidents, and Branch events separately. Do not ingest incidents as alerts or collapse Branch review into canonical status. Preserve raw source fields in namespaced `domain_data`; report unmappable values.
4. Compare counts, IDs, source statuses, severities, time ranges, dedupe keys, references and evidence availability. Vault has audit rows; no separate append-only Branch review audit was identified in the inspected repository paths.
5. Shadow-read/compare while source systems remain authoritative. Then switch to one writer for lifecycle actions; adapters proxy to authority. Reconcile drift before disabling any writer.
6. Retain source rows and read-only compatibility mappings through the rollback/retention window. Delete nothing or repoint Vault evidence foreign keys in initial rollout.

Branch dual-write is risky because persistence may be SQL-family or Mongo and event commits are not transactional with notifications/WebSocket effects. Prefer a durable local outbox/retry record before promising delivery. Document source of truth by phase.

## 7. Security, reliability and idempotency

- Authenticate producers with mTLS or rotated scoped service tokens bound to `use_case`/`producer`. Authenticate operators with platform identity and scopes for list, read sensitive metadata, acknowledge, resolve, dismiss, audit and notification administration. Scope by tenant/branch/use-case. The shared Vault POC key is not adequate service identity and is public when bundled in browser JS.
- Minimize sensitive data. Do not store face images, embeddings, credentials, RTSP URLs, frames or signed evidence URLs. Use opaque evidence references and authorized Evidence Service access. Bound metadata size/depth, enforce key policy, redact and safely escape rendered strings.
- Enforce uniqueness transactionally on producer scope/idempotency key and `(use_case,producer,source_event_id)`; store canonical request hash. Same key/hash replays original result; different hash conflicts. Retain keys at least for the producer retry horizon.
- Distinguish delivery idempotency from episode dedupe. Scope episode key by use case, producer and source discriminator. Declare cooldown/reopen, version, `last_seen_at`, count and severity escalation merge semantics. Never merge matching type/camera values across unrelated domains.
- Retry timeouts, 429 and 5xx with exponential backoff, jitter, bounded attempts, `Retry-After`, and same idempotency key. Do not retry other 4xx without correction. Use finite timeouts, circuit breaker and load shedding. Queue overflow must be observable and must not silently drop high-severity alerts; Vault currently logs queue drops, so durability needs design attention.
- Commit alert, audit and outbox atomically. Notification worker tracks attempts, redacts errors, classifies failures, backs off, dead-letters, and supports authorized manual retry. Do not send over network inside request/DB transaction. Acknowledgment is distinct from delivery receipt.
- Lifecycle writes use optimistic row versions, transition checks and actor provenance. Audit is append-only/access-controlled. Decide retention/legal-hold behavior before purge/partition. Alert Service does not implicitly own Vault legal hold obligations.
- Prevent webhook SSRF: admin-configured/allowlisted destinations, managed secrets, constrained redirects/private addresses, fixed payload templates; callers cannot submit arbitrary URLs.

## 8. Responsibility split

| Common Alert Service | Remains in use-case services |
|---|---|
| Canonical alert identity/source refs; shared list/detail/filter; common lifecycle actions; canonical audit; idempotent ingestion; optional notification outbox/channels and delivery health. | Detection/tracking/analytics, thresholds and domain dedupe, deciding when to alert, source event IDs/domain metadata, evidence capture/retention/storage, cameras/streams, Vault authorization/session logic, Branch review/report/analytics, Vault incident workflow until separately decided, domain dashboard/brief and compatibility APIs. |

## 9. Phased migration and test strategy

1. **Contract approval/baseline:** approve field semantics, status policies, identity, source references, ownership, retry and notification policy. Snapshot OpenAPI and representative fixtures. Add missing Branch API/repository/WebSocket characterization tests.
2. **Service foundation (future work):** isolated Alert Service on port 8012, owned schema/migrations, producer auth, audit, idempotency, list/detail/filter, lifecycle concurrency, outbox. Test without live use-case dependencies.
3. **Vault producer integration:** adapter at Vault boundary. Shadow ingest while existing rules/persistence remain authoritative; compare payload/counts. Keep Vault API adapter and incidents. Move lifecycle authority only with single-writer/reconciliation plan; retain evidence/incident FK compatibility.
4. **Branch producer integration:** adapt `alert_service.handle_signal` after source event commit; verify SQL and Mongo parity. Keep Branch event storage and legacy WebSocket projection. Test webhook and dedupe/evidence behavior; shift notification owner only after duplicate suppression/retries work.
5. **Frontend consolidation (later):** use common client only after compatibility is stable; retain Branch review/report and Vault incident/evidence UI. Validate auth and CORS.
6. **Decommission (separate approval):** only after reconciliation, retention/rollback period and explicit approval; out of scope here.

Recommended tests: schema/client compatibility; adapter fixtures; replay/conflict/concurrent duplicate ingestion; transition matrix and optimistic concurrency; atomic audit/outbox failure; cursor stability/filter scope; auth and redaction; retry/dead-letter/SSRF with local fake receiver; migration dry-run/checksum/reconciliation on restored DB copies; Vault API characterization; Branch SQL/Mongo parity; Branch WebSocket/reconnect payload; frontend route/status smoke tests. Do not use cameras, ML, Qdrant or production notification destinations in contract tests.

## 10. Remaining risks and unresolved migration questions

1. Who owns Vault alert rows after lifecycle cutover, given `vault_evidence.alert_id` and incident/audit references? The v1 adapter must preserve source IDs or maintain a durable mapping; the final migration choice remains open.
2. Should all Branch detector events become canonical alerts, or only policy-qualified severities? Today all signals are events while evidence is policy-limited.
3. Is Branch Mongo parity a migration requirement or can target persistence be SQL-only?
4. Which enterprise identity provider and tenant model will replace the v1 scoped bearer-token configuration before production rollout?
5. What retention, legal hold, deletion, evidence resolution and audit export rules apply?
6. Is a consolidated live feed required? The first adapters retain current transports; any later feed needs replay/cursor semantics.
7. What availability objective and retry/dead-letter operational process are required?

V1 decisions for source IDs, severity mapping, lifecycle/source-review separation, service/operator authentication, notification scope, and independent schema ownership are fixed in `docs/alert-service-contract.md` and are no longer blockers to implementing the isolated service. The contract review confirmed these choices preserve both inspected domains without altering existing APIs or tables.

## 11. Inspected paths

Vault: `backend/vault-monitoring/app/db/models/vault_room.py`, `app/db/vault_monitoring_repository.py`, `app/services/vault_alert_rules.py`, `app/services/vault_alert_persistence.py`, `app/services/vault_event_publisher.py`, `app/api/routes/alerts.py`, `app/api/routes/incidents.py`, migrations `20261026_vault_incidents_evidence_audit.sql` and `20261026_vault_alerts_stage3.sql`.

Branch: `backend/branch-exterior-monitoring/app/models/orm.py`, `app/schemas/event.py`, `app/db/repositories/interfaces.py`, `sql_repo.py`, `mongo_repo.py`, `app/services/alert_service.py`, `app/services/notification_service.py`, `app/api/routes/events.py`, `dashboard.py`, `brief.py`, `app/ws/manager.py`, `app/api/routes/ws.py`.

Frontend: `frontend/src/api/alerts.js`, `src/hooks/useVaultAlerts.js`, `src/pages/VaultAlerts.jsx`, `src/pages/VaultIncident.jsx`, `src/branch-exterior/api.js`, `feed.js`, `AlertsDashboardPage.jsx`, `LiveMonitoringPage.jsx`, and `SecurityBriefPage.jsx`.

At the time this design was first written, no application code, database, migration, frontend API, approved planning document, or legacy file was changed. The subsequent independent implementation is recorded under `backend/services/alert_service/`; it does not integrate or modify the legacy use cases.
