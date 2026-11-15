import test from 'node:test';
import assert from 'node:assert/strict';
import { readReplayContext, readVaultUi, restoredReplay, saveReplayContext, saveVaultUi, vaultUiFromSearch } from './replayStorage.js';

const values = new Map();
globalThis.localStorage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };

test('new users keep Entrance default; valid URL view/source override saved preferences', () => {
  values.clear();
  assert.equal(readVaultUi().view, 'entrance');
  saveVaultUi({ view: 'room', source: 'upload', scope: 'events', password: 'never-store' });
  assert.deepEqual(readVaultUi(), { view: 'room', source: 'upload', scope: 'events' });
  assert.deepEqual(vaultUiFromSearch('?view=zones&source=rtsp'), { view: 'zones', source: 'rtsp', scope: 'events' });
  assert.equal(vaultUiFromSearch('?view=invalid').view, 'room');
  assert.ok(![...values.values()].join().includes('never-store'));
});

test('only committed replay identifiers are persisted; frames/events/credentials are never cached', () => {
  values.clear();
  assert.equal(readReplayContext(), null);
  saveReplayContext({ sessionId: 'old-replay', sourceId: 'old-source', profileId: 'upload', events: ['large-history'], apiKey: 'never-store' });
  const expected = { sessionId: 'old-replay', sourceId: 'old-source', profileId: 'upload' };
  assert.deepEqual(readReplayContext(), expected);
  assert.equal(restoredReplay(expected).session_id, 'old-replay');
  assert.equal(restoredReplay(expected).status, 'restoring');
  assert.equal(restoredReplay(expected).source_id, 'old-source');
  assert.deepEqual(restoredReplay(expected).events, []); // Re-fetched from the durable API.
  assert.ok(![...values.values()].join().includes('never-store'));
  assert.ok(![...values.values()].join().includes('large-history'));
  saveReplayContext({ sessionId: 'invalid/path', sourceId: 'new', profileId: 'upload' });
  assert.deepEqual(readReplayContext(), expected);
  saveReplayContext({ sessionId: 'new-replay', sourceId: 'new-source', profileId: 'camera-2' });
  assert.equal(readReplayContext().sessionId, 'new-replay');
});

test('corrupt or old-version storage is ignored without breaking the page', () => {
  values.clear(); values.set('vault-room-replay:v1', '{'); values.set('vault-room-ui:v1', 'null');
  assert.equal(readReplayContext(), null);
  assert.equal(readVaultUi().view, 'entrance');
  values.set('vault-room-replay:v1', JSON.stringify({ version: 0, sessionId: 'old', sourceId: 'old', profileId: 'upload' }));
  assert.equal(readReplayContext(), null);
});
