# Stage 3 implementation report

## Delivered

- M0 findings: `docs/vault-alerts-inspection.md`.
- Manual reversible SQL migrations: `20261026_cloudinary_evidence.sql`, `20261026_vault_incidents_evidence_audit.sql`, and `20261026_vault_alerts_stage3.sql`, each with a matching `_down.sql` file. The Stage 3 migration adds public UUID session references, durable alert-condition episodes, alert/incident/evidence fields and indexes, an incident number sequence, and an append-only audit trigger.
- `get_operator()` derives one generic shared-key operator identity. There are no roles or individual accounts; accountability is shared-key level.
- Pure rule matrix, YAML/Pydantic settings, bounded persistent alert worker, alert/incident API routes, lifecycle and status API changes, and committed alert-channel events over the existing SSE endpoint.
- Stage 2 evidence service extensions for thumbnails, metadata, signed batch access, result callbacks, and blocked-delete conflicts. Alert creation now hands eligible event-time clean frames to a background JPEG/evidence queue; the inference thread does not encode or upload them.
- Automatic captures for unauthorized entry and excess-person alerts are written to a bounded local spool with JSON sidecars; startup recovery queues surviving sidecars, and successful uploads remove both files.
- API reference: `docs/vault-alerts-api.md`.

## Configuration

The `vault_alerts` YAML block contains `count_shortfall_grace_seconds`, `clear_seconds`, `episode_gap_seconds`, `reopen_cooldown_seconds`, `touch_interval_seconds`, `incident.auto_create_min_severity`, and evidence enablement, per-type switches, JPEG settings, capture limits, and spool directory/limit values.

## Events and phase behavior

Alert events use `{event_id, type, occurred_at, entity, entity_version, session_ref, incident_id, alert_id, data}` and are emitted through `/api/v1/vault-room/events` after persistence. Authentication outcomes exposed by the service include identity-attempt exhaustion, inactive/unknown identity, duplicate custodian, and final liveness failure; these feed U-B. U-A uses stable count greater than the verified custodian count. Camera health comes from the existing frame-age signals. The room ticker evaluates the existing six-minute room expiry and persists `SESSION_EXPIRED`; no separate timer was added. IDLE presence is intentionally not monitored. Session-start evidence remains deferred.

## Remaining before Stage 3 is complete

- Audit oldest-item eviction, exercise spool crash recovery, and ensure recovery drains more items than the in-memory queue capacity in one startup. Spool bounds are applied, but evictions are not yet written to the audit table.
- Enforce capture caps, minimum spacing, re-alert capture intervals, and shared-incident capture deduplication. Current automatic capture handles eligible alert creation only.
- Add concurrency coverage for two PostgreSQL workers and the complete alert state/rule/evidence policy matrix.
- Apply both migration directions against a disposable real PostgreSQL database. `pg_isready` reports the local server accepting connections, but `psql -w -lqt` fails with “no password supplied”; no migration was applied.
- Fix or isolate the existing full-suite failures before release.

## Verification

- Focused Stage 3 and vault regression selection: **61 passed**.
- Full backend suite: **213 passed, 9 failed**. Five failures are employee registration tests hitting the configured external service path; four liveness tests are affected by shared active-session state in the test process. These are outside the focused Stage 3 changes but remain release blockers.
- After adding spool recovery, the queue-full regression test passed. The full suite has not been rerun after that final evidence-queue change.
- `docs/vault-alerts-api.md` lists the exposed routes, request examples, event envelope, and error codes. OpenAPI loads successfully with 53 paths.

Do not begin frontend mapping until the remaining evidence spool/cap requirements and PostgreSQL migration verification are complete.

## Frontend route note (added after the frontend route consolidation)

Frontend only; this report's backend scope, API paths and events are unchanged (the alerts API is still under `/api/v1/...` and events on `/api/v1/vault-room/events`). The Vault alert feed page moved from `/vault-alerts` to `/alerts/vault` (the first of three Alerts tabs); `/vault-alerts` redirects with its query string. The incident page stays at `/vault-alerts/incidents/:id`. The page still reads Vault's own alerts API, not the Alert Service. See `docs/migration-plan.md` section 11.
