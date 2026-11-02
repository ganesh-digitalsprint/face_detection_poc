# Alert Service Contract v1

**Status:** Final contract baseline for the independent service implementation. This contract defines the initial platform wire contract; it does not change Vault or Branch APIs or schemas.

## 1. Decisions

1. **Service/source identity:** canonical IDs are service UUIDs. The immutable source key is `(use_case, producer, source_event_id)` and is unique. Source IDs are opaque UTF-8 strings, case-sensitive, length 1–200, and must not contain credentials or personal data. A source event ID denotes one alert episode and is never reused for a later recurrence. Producers send a new source ID for a new episode. `source_event_version` is a positive, monotonically increasing integer for updates to that same episode.
2. **Severity:** canonical values are `INFO`, `WARNING`, `HIGH`, `CRITICAL`. Vault values map identically. Branch values map `info→INFO`, `low→WARNING`, `medium→WARNING`, `high→HIGH`, `critical→CRITICAL`. Preserve the exact supplied value in `source_severity`. Unknown values are rejected with 422; no threshold or detector behavior changes.
3. **Lifecycle and source review:** canonical alert status values are `OPEN`, `ACKNOWLEDGED`, `RESOLVED`, `DISMISSED`. Allowed edges are `OPEN→ACKNOWLEDGED|RESOLVED|DISMISSED` and `ACKNOWLEDGED→RESOLVED|DISMISSED`; terminal states do not reopen. A recurrence after terminal state uses a new source event ID. Source-specific review (`under_review`, `confirmed`, `false_positive`, Branch `closed`) is retained separately as `source_status` and never implicitly changes canonical lifecycle. Vault incidents remain Vault-owned and are not alerts.
4. **Authentication:** producer calls use `Authorization: Bearer <producer-token>`; each token is configured server-side for exactly one `use_case` and `producer`. Operator calls use a separate `Authorization: Bearer <operator-token>` configured for an actor ID and allowed use-case scopes (`*` or an explicit list). Tokens are compared in constant time, never logged, and must be rotated through deployment secrets. Missing server token configuration fails closed with 503; invalid credentials return 401, insufficient scope 403. Public browser bundles are never trusted with these tokens.
5. **Notifications:** initial delivery scope is Branch's existing configured webhook behavior for newly created Branch events only. The payload preserves legacy keys `text`, `event_id`, `severity`, `scenario`, `camera`, `zone`, `confidence`, and `created_at`, with canonical `alert_id` and `delivery_id` added. Severity is the original Branch value. Alert Service sends this fixed, sanitized payload only to a server-configured destination; no producer-supplied URL or arbitrary destination is accepted. Vault room SSE remains Vault-owned and is not replaced; Vault ingestion creates no webhook job in v1. Delivery is asynchronous, durable, at-least-once, retryable, and independently recorded; no destination configured means no delivery job. Exactly-once delivery is not promised.
6. **Ownership:** Alert Service owns only its own schema and canonical lifecycle/audit/outbox. Existing Vault PostgreSQL tables and Branch SQL/Mongo `events` remain source-of-truth during initial integration. No existing table is altered by this contract.

## 2. HTTP conventions

- Base path `/api/v1`; planned host port `8012`; JSON request/response bodies; timestamps are timezone-aware RFC3339 in UTC.
- All responses include or can be correlated with `X-Request-ID`. Errors use `{"detail":{"code":"...","message":"...","request_id":"..."}}`.
- Unknown request fields are rejected; JSON metadata is bounded by implementation limits and cannot contain evidence bytes, credentials, face data, or signed URLs.
- `Idempotency-Key` is required for producer ingestion, 1–200 chars. Identical key and canonical body replay the original alert with HTTP 200. Same key with changed body returns 409 `IDEMPOTENCY_CONFLICT`.

## 3. Producer API

### `POST /api/v1/alerts`

Required body fields: `schema_version` (`1`), `source_event_id`, `source_event_type`, `source_event_version` (positive integer), `occurred_at`, `severity` (producer vocabulary), `title`, and `summary`. Optional fields: `category`, `deduplication_key`, `first_seen_at`, `last_seen_at`, `source_status`, `resource_refs`, `domain_data`, and `evidence_refs`. The authenticated token supplies `use_case` and `producer`; clients cannot override them in the body. The `Idempotency-Key` header is separate from `deduplication_key`.

First accepted creation returns 201; an identical replay returns 200. The service returns its UUID, source key, source version, canonical and source severity, lifecycle state, timestamps, and `row_version`. A second idempotency key for an already-known source key returns the existing alert only if the incoming canonical payload matches current source content; otherwise return 409 `SOURCE_EVENT_CONFLICT` and require the update operation.

### `PUT /api/v1/alerts/source-events/{source_event_id}`

Updates producer-owned fields for the token's configured use case/producer. Require `If-Match: "<source_event_version>"`; body contains the next strictly greater `source_event_version` and the same producer fields as ingestion. It does not alter common lifecycle, audit actor, or notification configuration. A stale version returns 409 `SOURCE_VERSION_CONFLICT`. Updates to a terminal alert's source metadata are permitted, but status remains terminal and a new episode requires a new source ID.

There is no batch endpoint in v1; producers send one item per request so partial failure and replay semantics stay unambiguous.

## 4. Operator API

- `GET /api/v1/alerts`: filters `use_case`, `producer`, `status`, canonical `severity`, `source_event_type`, `source_event_id`, `category`, `from`, `to`; `sort=newest|oldest`; cursor pagination; `limit` 1–100. Operators may only query their configured scopes. Stable order is `(occurred_at,id)`.
- `GET /api/v1/alerts/{alert_id}`: full canonical record, source references, safe metadata/evidence references, current source version, `row_version`, and allowed lifecycle actions.
- `GET /api/v1/alerts/{alert_id}/audit`: append-only event history for the alert.
- `GET /api/v1/alerts/summary`: counts by status/severity with the same query scope and filters.
- `GET /api/v1/alerts/meta`: fixed canonical enums and scope-safe categories; does not expose configured secrets or infrastructure details.
- `POST /api/v1/alerts/{alert_id}/acknowledgements`, `/resolution`, `/dismissal`: body `{ "note": "...", "expected_version": 4 }`; note optional for acknowledge, required for resolve/dismiss. Requires the current `row_version` via `expected_version`. A repeated request with stale version returns 409 unless the alert already reflects the same requested action, in which case it returns current state idempotently. An invalid transition returns 409 `INVALID_TRANSITION`; version mismatch returns 409 `VERSION_CONFLICT`; missing resource 404.
- `GET /api/v1/notifications/{delivery_id}`: scoped operator view of a delivery state, attempts and sanitized last error. Delivery retry is service-managed; no public arbitrary retry/destination endpoint in v1.

Health endpoint `GET /health` is unauthenticated and reports process readiness without database credentials/details. Liveness is separate from readiness if introduced.

## 5. Canonical object

```json
{
  "id": "service-uuid",
  "schema_version": 1,
  "use_case": "branch_exterior",
  "producer": "branch-exterior-monitoring",
  "source_event_id": "opaque-immutable-id",
  "source_event_type": "loitering",
  "source_event_version": 1,
  "category": "security",
  "severity": "WARNING",
  "source_severity": "medium",
  "title": "Loitering detected",
  "summary": "...",
  "status": "OPEN",
  "source_status": "open",
  "occurred_at": "2026-10-28T12:00:00Z",
  "first_seen_at": "2026-10-28T12:00:00Z",
  "last_seen_at": "2026-10-28T12:00:00Z",
  "received_at": "2026-10-28T12:00:01Z",
  "updated_at": "2026-10-28T12:00:01Z",
  "resource_refs": {"camera_id": "...", "zone_id": "..."},
  "domain_data": {"schema_version": "branch-event/1", "confidence": 0.91},
  "evidence_refs": [],
  "occurrence_count": 1,
  "row_version": 1,
  "acknowledged_at": null,
  "acknowledged_by": null,
  "resolved_at": null,
  "resolved_by": null,
  "resolution_note": null,
  "resolution_source": null,
  "dismissed_at": null,
  "dismissed_by": null
}
```

`resource_refs`, `domain_data`, and `evidence_refs` preserve producer-specific context without claiming ownership. The source key and raw source severity remain queryable and auditable.

## 6. Persistence and integration guarantees

The service owns new `alerts`, `alert_audit`, `notification_outbox`, and source/idempotency uniqueness data only. Alert, audit, and notification job insertion commit atomically. Producer retries use the same idempotency key. Source event identity is unique by authenticated producer scope. Episode deduplication is producer-provided and informational in v1; the service does not merge distinct source IDs or apply a cross-domain cooldown.

The first adapters preserve `/api/v1/alerts` and `/api/v1/incidents` in Vault and `/api/events`, Branch reports/dashboard/brief, and `/api/ws/alerts`. Vault compatibility keeps old alert IDs/source mapping for `vault_evidence.alert_id`; Branch source review remains separate. During shadow ingestion, source stores remain authoritative and no Alert Service operator writes are enabled to legacy records. Cutover later must pick one lifecycle writer, reconcile rows/audits, and retain rollback mappings. No deletion or in-place schema change is part of v1.

The Branch-compatible webhook payload uses `event_id=source_event_id`, `scenario=source_event_type`, original `source_severity`, camera/zone names when provided in `resource_refs` (otherwise IDs), confidence from `domain_data` (default 0), and the source occurrence time. It also includes canonical `alert_id` and stable `delivery_id` so receivers can de-duplicate retries. Vault alerts do not enqueue this Branch webhook.

## 7. Required implementation tests

Contract validation for both producer scopes and severity maps; authentication/scope matrix; source ID collision and idempotency replay/conflict; monotonic source version/If-Match behavior; canonical lifecycle transition matrix, required notes and optimistic concurrency; atomic audit/outbox persistence; cursor stability and use-case scoping; JSON bounds/redaction; notification sanitization/retry with a mocked HTTP receiver; `/openapi.json` contract snapshot. Tests use an isolated local SQLite database and mocked producer/auth/notification inputs; no Vault or Branch app imports, cameras, ML, PostgreSQL, Qdrant or real webhook calls.
