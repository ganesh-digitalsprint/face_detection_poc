# Vault Room activity timeline chronology

The Activity Events timeline now requests `order=asc` from the existing
`/api/v1/vault-room/sessions/{session_id}/activity-events` endpoint. The API's
default remains newest first for existing callers.

Uploaded replay events sort by source-video timestamp, then creation timestamp,
then event ID. Creation time and ID provide deterministic ordering for simultaneous
events without changing persisted records. The frontend retains sub-millisecond
timestamp precision when comparing ties. Live activity uses creation time and ID.
Merging replaces duplicate IDs while retaining this ordering.

Pagination requests globally oldest-first pages. Loading more appends the next
page. Polling refreshes the loaded prefix; once caught up, it follows the new tail
across page boundaries automatically. It does not reverse newest-first pages.
The same ordering applies to the expanded Event Log and filtered display.

## Validation

- Backend activity tests: 22 passed, including source-time ordering, timestamp/ID
  ties, pagination, incremental insertion, unchanged default ordering and invalid
  order validation.
- Frontend activity utility tests: 6 passed, including deduplication, equal source
  times, microsecond ties, refresh ordering, incremental updates and pagination
  across the 25-row boundary.
- Frontend production build passed; the existing bundle-size warning remains.
- A fresh run of `temp/vault_monitoring_hand_raise_updated_25s.mp4` completed all
  120 sampled frames. Replay ID: `3f18bddd75b94e7ca8affc64dd8bf219`.
- Full and limit-two API pages returned the same six unique records:

| Source time | Activity |
| --- | --- |
| 1.25 s | PERSON_DETECTED, Track 2 |
| 1.25 s | PERSON_DETECTED, Track 1 |
| 1.25 s | PERSON_ENTERED |
| 1.25 s | SESSION_STARTED |
| 2.708333 s | VAULT_AREA_INTERACTION |
| 14.791667 s | VAULT_DOOR_INTERACTION |

The worker reported the unchanged workflow confirmation threshold of 0.5 seconds.
All six evidence JPEGs were retrieved successfully. No replay alerts were created.

Browser validation used the real persisted API records, with launch requests
bound to the completed validation replay to avoid duplicate inference. For a
deterministic polling test, read-only responses exposed the real records as four,
then five, then six. Each new row appeared at the bottom and prior row positions
remained identical. Manual refresh, page reload with the same replay selected,
the expanded oldest-first Event Log and full-resolution evidence viewer passed.
This response staging tests rendering and polling, rather than claiming to time
the browser test against asynchronous database commits.

## Files changed

Backend paths are relative to `backend/use_cases/vault_monitoring`:

- `app/api/routes/vault_activity.py`
- `app/services/vault_activity.py` (retrieval ordering only)
- `tests/test_vault_activity.py`
- `docs/vault-room-activity-chronology.md`

Frontend paths are relative to the repository root:

- `frontend/src/use-cases/vault-monitoring/utils/activityEvents.js`
- `frontend/src/use-cases/vault-monitoring/utils/activityEvents.test.js`
- `frontend/src/use-cases/vault-monitoring/hooks/useVaultActivityEvents.js`
- `frontend/src/use-cases/vault-monitoring/components/vault/VaultActivityEvents.jsx`

Detection, workflow transitions, ROI geometry, inference, activity persistence,
authorization, security alerts and other use cases were not changed.
