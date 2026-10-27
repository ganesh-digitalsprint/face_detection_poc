# Vault Alerts API contract

This contract reflects the FastAPI routes in `app.main:app`. Base prefix: `/api/v1`. The shared `X-API-Key` authorizes all POC operator actions, including incident updates, legal holds, evidence access, and evidence deletion. There are no roles or separate admin key in this POC.

## Alerts

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/alerts` | Cursor list; `scope`, `status`, `severity`, `alert_type`, camera/session/incident and time filters; `sort`, `limit`, `cursor` |
| GET | `/alerts/summary` | Counts over the filtered alert set |
| GET | `/alerts/meta` | Enum values, cameras, evidence limits and incident transitions |
| GET | `/alerts/{alert_id}` | Alert detail |
| POST | `/alerts/{alert_id}/{action}` | `acknowledge`, `resolve` or `dismiss`; body has `note` and optional `expected_version` |
| POST | `/alerts/{alert_id}/incident` | Idempotently open/link an incident |
| POST | `/alerts/{alert_id}/evidence` | Multipart single-file evidence upload |

Example list response:

```json
{"items": [], "next_cursor": null, "has_more": false}
```

Example action request:

```json
{"note": "Reviewed camera recording", "expected_version": 2}
```

## Incidents

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/incidents/{incident_id}` | Incident with linked alerts, evidence metadata, comments, timeline and session summary |
| PATCH | `/incidents/{incident_id}/status` | Validated status transition; resolve/close requires a note |
| POST | `/incidents/{incident_id}/hold` | Set or clear a legal hold with reason |
| POST | `/incidents/{incident_id}/comments` | Append a trimmed comment; author is derived from the operator credential |
| POST | `/incidents/{incident_id}/evidence` | Multipart single-file evidence upload |

## Evidence

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/evidence/access` | Batch signed `thumb` or `full` access for up to 50 IDs |
| GET | `/evidence/{evidence_id}` | Evidence metadata without storage URLs |
| GET | `/evidence/{evidence_id}/access-url` | Signed full image URL (legacy single-item access) |
| DELETE | `/evidence/{evidence_id}?reason=...` | Delete evidence, blocked for active incidents and legal holds |

Example batch access response:

```json
{"items": [{"id": "<evidence-id>", "url": "<short-lived-signed-url>", "expires_at": "2026-10-26T12:00:00Z", "variant_used": "thumb"}]}
```

## Errors

Expected domain codes include `ALERT_NOT_FOUND`, `INCIDENT_NOT_FOUND`, `INVALID_TRANSITION`, `VERSION_CONFLICT`, `NOTE_REQUIRED`, `HIGH_SEVERITY_CANNOT_BE_DISMISSED`, `EVIDENCE_PREVIOUSLY_REMOVED`, `EVIDENCE_NOT_FOUND`, and `STORAGE_UNAVAILABLE`. FastAPI validation and authentication errors follow the application's existing `detail` response convention.

## Events

Events are sent over the existing `/api/v1/vault-room/events` Server-Sent Events stream. Each committed alert-channel event uses `{event_id, type, occurred_at, entity: {type, id}, entity_version, session_ref, incident_id, alert_id, data}`. Types include `alert.created`, `alert.updated`, `incident.created`, `incident.updated`, `evidence.available`, `evidence.upload_failed`, `comment.created`, `session.started`, and `session.expired`. REST is authoritative after disconnects.
