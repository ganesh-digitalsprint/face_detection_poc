import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mergeTickerEvents, tickerDetailLocation } from './tickerModel.js';

test('initial API events and WebSocket events merge once by stable source event ID in newest-first order', () => {
  const initial = [
    { id:'event-a', created_at:'2026-11-16T10:00:00Z', message:'Original' },
    { id:'event-b', created_at:'2026-11-16T09:00:00Z' },
  ];
  const merged = mergeTickerEvents(initial, [
    { id:'event-a', created_at:'2026-11-16T10:00:00Z', message:'Updated by websocket' },
    { id:'event-c', created_at:'2026-11-16T11:00:00Z' },
  ]);
  assert.deepEqual(merged.map((event) => event.id), ['event-c', 'event-a', 'event-b']);
  assert.equal(merged[1].message, 'Updated by websocket');
});

test('different event IDs remain separate even when camera, track, and description match', () => {
  const events = mergeTickerEvents([], [
    { id:'event-1', camera_id:'camera-1', track_ids:[2], message:'Track running', created_at:'2026-11-16T10:00:00Z' },
    { id:'event-2', camera_id:'camera-1', track_ids:[2], message:'Track running', created_at:'2026-11-16T09:59:00Z' },
  ]);
  assert.deepEqual(events.map((event) => event.id), ['event-1', 'event-2']);
});

test('ticker opens source-event details on the current page and preserves other query filters', () => {
  assert.deepEqual(tickerDetailLocation('/branch-exterior/live', '?camera=cam-1&tab=alerts', 'source /event'), {
    pathname:'/branch-exterior/live', search:'?camera=cam-1&tab=alerts&event=source+%2Fevent',
  });
});
