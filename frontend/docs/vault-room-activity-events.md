# Vault Room Activity Events UI

The Vault Room Camera's existing alert card adds an **Events** tab, category pills,
and a scrollable informational timeline. Active/History alert queries, acknowledgement,
history, evidence, and links retain their existing implementations. Operational
activities never become alert cards. Zones & Regions and Entrance Camera are unchanged.

The component supports the four Phase 1 types, with a generic Activity icon/category
for future backend event types. Door filters are available for future events but
do not fabricate any results. Category pills filter the loaded history; Load more
continues fetching additional pages, including while a category is selected.

## Existing backend contract

`api/activityEvents.js` exposes a JSDoc-typed service using the existing Axios client
and configured `X-API-Key`. It calls the implemented endpoints:

- `GET /api/v1/vault-room/sessions/{session_id}/activity-events`
- `GET /api/v1/vault-room/activity-events/{event_id}`
- `GET /api/v1/vault-room/activity-events/{event_id}/evidence`

History returns `{items,total,limit,offset}`. The service documents all raw activity
fields. Queries include source, source ID, replay mode, and 25-row pagination.
Live session IDs come from room state; replay session IDs come from video-session
responses, rather than the replay worker's internal authorization session ID.
Live source IDs use the selected region profile; replay source IDs use the replay UUID.
Without a session, the UI waits rather than fetching unrelated recent history.

The existing room SSE stream's `activity.created` messages invalidate the current
session's feed. A three-second visible-page polling fallback also handles replay,
reconnects, and activity writes completing after video processing ends. Refresh
reloads all loaded pages; overlapping IDs are deduplicated. Aborted requests and
render-time context guards prevent old rows from flashing after session, source,
profile, file, mode, or tab changes.

No backend-unavailable path silently substitutes mock data. Loading, empty, API
failure/retry, completed/stopped replay, and unavailable evidence states are explicit.

## Evidence and time

Replay timestamps display source video time to tenths of a second. Live timestamps
display local wall time. The event detail viewer includes both recorded time and
source video time, track IDs, count, zone, camera/session IDs, mode, and metadata.

Thumbnails and full evidence use the shared `loadSnapshot` authenticated blob
resource utility. It aborts stale reads and revokes object URLs on unmount/change.
The native dialog follows the existing snapshot-viewer pattern, provides modal
keyboard focus, Escape dismissal and focus restoration, and preserves image aspect
ratio. Evidence is fetched from its known API path, never arbitrary event URLs.

## Verification

Unit tests cover timestamp formatting, future-type categories, zone labels and
deduplication. Browser integration checks use mocked backend responses only in the
test harness: live/replay timeline, SSE/polling, pagination, filters, API error/retry,
authenticated evidence, event details/log, source/session/file clearing and responsive
widths (1440, 1366, 1024, 768, 390). Production UI consumes actual API results only.
