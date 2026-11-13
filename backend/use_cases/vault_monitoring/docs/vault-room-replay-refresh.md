# Vault Room replay refresh and durable activity restoration

## Causes

`VaultAccess` initialized its camera view to Entrance on every mount. Camera
source and replay alert/Event subview also existed only in component state.
Neither the URL nor a saved preference restored those choices.

`useVaultRoomReplay` kept the replay ID only in React state/ref. Its unmount
cleanup, source deselection and file selection disposed the temporary worker
and cleared the replay context. Preparing a new upload cleared the old session
before the new start succeeded. After refresh, the activity hook had no session
or source ID with which to query durable history. The activity records themselves
were already stored correctly in PostgreSQL; worker cleanup did not delete them.

## Restoration strategy

- Camera view and source are represented by the existing route's `view` and
  `source` query parameters. Valid URL choices take precedence; saved preferences
  restore returning navigation without query parameters. A new browser still
  defaults to Entrance. The Replay Active/History/Events subview is also saved.
- `vault-room-replay:v1` stores only a version plus committed session ID, source
  ID and profile ID. `vault-room-ui:v1` stores view/source/subview preferences.
  No events, frames, images, video data, credentials, worker status or timestamps
  are cached in browser storage.
- Mount restores the identifier context and asynchronously calls the existing
  replay status and scoped activity APIs. Current source time, processing status,
  progress and processed preview come from the worker when available. Restoration
  never uploads the file again or starts another worker.
- A status 404 retains the IDs and independently loads PostgreSQL-backed activity
  history and evidence. The UI explains that the temporary worker is unavailable;
  it does not mistake worker absence for deleted activity. Full video playback or
  the worker's former processing state cannot be reconstructed once that worker
  and temporary video are gone; durable event evidence remains accessible.
- Navigation/unmount aborts browser requests without stopping/deleting the worker.
  Existing backend TTL cleanup remains unchanged. Explicit processing controls
  retain their previous meaning.
- Choosing/preparing another file keeps the old activity context. Only a
  successful explicit start commits and saves the new ID, resets replay-specific
  state and changes the activity scope. Upload/start failures retain the previous
  context. After successful replacement, the previous temporary worker may be
  retired through the existing DELETE API; its PostgreSQL activity and evidence
  are not deleted.
- Request generations and abort/scope guards reject old status, frame and activity
  responses. Same-context refreshes retain loaded rows during pending requests,
  failures and view changes. Loaded pages retain their existing chronological
  sort and ID deduplication; no event-type ordering was introduced.
- New-file preview metadata is kept separate from committed replay state, so the
  Zones video scrubber can prepare a file without replacing the activity session.

## Automated checks

- Nine Node tests passed: three storage/navigation tests plus the existing six
  activity chronology/pagination/notification tests.
- Five Playwright browser regression tests passed. They cover completed-worker
  refresh, view/source/Events restoration, evidence, Zones refresh, SPA navigation,
  worker 404, transient activity errors, choosing a file without clearing history,
  in-progress refresh without duplicate upload/start, upload failure, start failure,
  successful context replacement, old delayed-response rejection and restoring the
  new context after refresh.
- Frontend production build passed to a temporary output directory. Existing
  bundle-size warning remains. The workspace lacked its declared Playwright runner
  installation, so the checked-in tests ran through the existing cached runner
  with imports adapted only in a temporary test copy; dependencies were unchanged.

## Real 25-second browser validation

Recording: `temp/vault_monitoring_hand_raise_updated_25s.mp4`.
The browser first restored the 11 actual durable records for the already-cleaned
session `a7652b00cd474737b1ffb158453e1d90` and retained them on refresh. Choosing the
recording for the next run also retained those rows until start succeeded.

A fresh replay, `e7bd57f3f5474e17ae8b6540537f7fe4`, then ran through the real UI,
decoder, RF-DETR, ByteTrack, MediaPipe Full, ROI engine and durable writer. An
isolated listener used the existing service environment and database to avoid
interrupting live monitoring. Browser requests were redirected to that listener;
upload/start/status/activity/evidence responses were real and were not fabricated.

- Exactly **one upload and one start** occurred.
- Refresh at source time **4.166667 seconds** reconnected to the same processing
  worker. Current status/source time and processed preview recovered.
- All **120 sampled frames** completed, yielding **11 persisted activity records**.
- Completion refresh, Events subview, Zones tab refresh, returning to Room and
  navigating through Dashboard all retained the exact UI/API chronological order.
- Full-resolution evidence (1280 pixels wide) opened before and after cleanup.
- After explicit validation-worker DELETE and another browser refresh, all 11
  activities and evidence still loaded correctly. No replacement worker started.
- Direct SQL inspection confirmed the database dialect is PostgreSQL and all 11
  activity-channel records remain in `vault_room_events`. Main port 8010 returned
  the same records and all 11 JPEGs after worker cleanup.
- No production alerts or authorization-session rows were created for this replay.
  Browser storage contained only the whitelisted identifier fields/preferences.

## Files changed

Frontend paths relative to the repository root:

- `frontend/src/use-cases/vault-monitoring/pages/VaultAccess.jsx`
- `frontend/src/use-cases/vault-monitoring/hooks/useVaultRoomReplay.js`
- `frontend/src/use-cases/vault-monitoring/hooks/useVaultActivityEvents.js`
- `frontend/src/use-cases/vault-monitoring/utils/replayStorage.js`
- `frontend/src/use-cases/vault-monitoring/utils/replayStorage.test.js`
- `frontend/src/use-cases/vault-monitoring/components/vault/VaultRoomCameraControls.jsx`
- `frontend/src/use-cases/vault-monitoring/components/vault/VaultRoomReplayAlerts.jsx`
- `frontend/src/use-cases/vault-monitoring/components/vault/VaultRoomReplayPreview.jsx`
- `frontend/src/use-cases/vault-monitoring/components/vault/VaultVideoScrubber.jsx`
- `frontend/e2e/vault-replay-restoration.spec.js`
- This report: `backend/use_cases/vault_monitoring/docs/vault-room-replay-refresh.md`.

No backend route, database schema, activity persistence, evidence storage,
detection/tracking/pose model, ROI configuration/priority, 0.5-second threshold,
authorization, security-alert rule or other use-case implementation was changed.
