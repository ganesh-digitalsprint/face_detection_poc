import { test } from 'node:test';
import assert from 'node:assert/strict';
import { branchEventDestination, findCommonAlert, mergeTickerEvents } from './tickerModel.js';

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

test('ticker uses the Common Alert ID while preserving the source event ID in the deep link', () => {
  assert.equal(branchEventDestination('source-event-1', { id:'common-alert-9' }),
    '/alerts?use_case=branch_exterior&alert_id=common-alert-9&source_event_id=source-event-1');
});

test('an unpublished ticker source opens the source-owned detail route', () => {
  assert.equal(branchEventDestination('source /event', null), '/branch-exterior/live?event=source%20%2Fevent');
});

test('missing ticker mapping performs a source-reference lookup and falls back only when unpublished', async () => {
  const sourceEventId='source-11';
  let query;
  const common=await findCommonAlert(sourceEventId,null,async(params)=>{
    query=params;
    return {items:[{id:'common-11',sourceEventId}]};
  });
  assert.deepEqual(query,{use_case:'branch_exterior',source_event_id:sourceEventId,limit:1});
  assert.equal(branchEventDestination(sourceEventId,common),'/alerts?use_case=branch_exterior&alert_id=common-11&source_event_id=source-11');
  const absent=await findCommonAlert('not-published',null,async()=>({items:[]}));
  assert.equal(branchEventDestination('not-published',absent),'/branch-exterior/live?event=not-published');
});
