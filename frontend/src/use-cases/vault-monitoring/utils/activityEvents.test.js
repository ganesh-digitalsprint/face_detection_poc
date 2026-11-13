import test from 'node:test';
import assert from 'node:assert/strict';
import { activityCategory, activityTime, activityVideoTime, activityZone, mergeActivities, latestActivityNotificationId, readChronologicalActivityPages } from './activityEvents.js';

test('later commits invalidate activity history without crossing replay sessions', () => {
  const scope={sessionId:'current',source:'upload',sourceId:'current',replay:true};
  const event=(id,session='current')=>({id,type:'activity.created',data:{session_id:session,source:'upload',source_id:session,replay:true}});
  const rows=[event('person')];
  assert.equal(latestActivityNotificationId(rows,scope),'person');
  rows.push(event('interaction'));
  assert.equal(latestActivityNotificationId(rows,scope),'interaction');
  rows.push(event('different-video','old'));
  assert.equal(latestActivityNotificationId(rows,scope),'interaction');
  assert.equal(latestActivityNotificationId(rows,{...scope,sourceId:'another-profile'}),undefined);
});

test('activity time uses source time for replay and safely handles invalid values', () => {
  assert.equal(activityVideoTime(61.39), '1:01.3');
  assert.equal(activityVideoTime(0), '0:00.0');
  assert.equal(activityVideoTime(null), '\u2014');
  assert.equal(activityTime({ replay: true, video_timestamp_seconds: 1.3 }), '0:01.3');
  assert.equal(activityTime({ created_at: 'invalid' }), '\u2014');
});
test('operational categories accept future types without classifying them as alerts', () => {
  assert.equal(activityCategory('PERSON_DETECTED'), 'Activity');
  assert.equal(activityCategory('PERSON_ENTERED'), 'Entry');
  assert.equal(activityCategory('VAULT_AREA_ENTERED'), 'Entry');
  assert.equal(activityCategory('VAULT_AREA_INTERACTION'), 'Activity');
  assert.equal(activityCategory('VAULT_DOOR_INTERACTION'), 'Door');
  assert.equal(activityCategory('ORNAMENT_AREA_INTERACTION'), 'Activity');
  assert.equal(activityCategory('TRAY_INTERACTION'), 'Activity');
  assert.equal(activityCategory('SESSION_STARTED'), 'System');
  assert.equal(activityCategory('VAULT_OPEN_DETECTED'), 'Door');
  assert.equal(activityCategory('FUTURE_ACTIVITY'), 'Activity');
  assert.equal(activityZone('vault_area_roi'), 'Vault Area');
  assert.equal(activityZone('future_zone'), 'future_zone');
});
test('overlapping pages deduplicate event IDs and retain newest record contents', () => {
  const first = { id: 'a', created_at: '2026-11-12T10:00:00Z', description: 'old' };
  const replacement = { ...first, description: 'updated' };
  const newer = { id: 'b', created_at: '2026-11-12T10:01:00Z' };
  assert.deepEqual(mergeActivities([first, newer, replacement, null]), [replacement, newer]);
});

test('replay chronology uses source time and backend-compatible microsecond/id tie keys', () => {
  const row = (id, time, created) => ({id,replay:true,video_timestamp_seconds:time,created_at:created});
  const first=row('z',1.25,'2026-11-13T01:00:00.000001Z');
  const second=row('a',1.25,'2026-11-13T06:30:00.000002+05:30');
  const tied=row('b',1.25,second.created_at);
  const later=row('0',2.708,'2026-11-13T00:00:00Z'); // Wall time must not override source time.
  assert.deepEqual(mergeActivities([later,tied,second,first]).map(e=>e.id),['z','a','b','0']);
  const initial=mergeActivities([tied,first,second]);
  const equalSourceNew=row('00',1.25,'2026-11-13T01:00:00.000003Z');
  const updated=mergeActivities([...initial,equalSourceNew,later,{...second,description:'refreshed evidence'}]);
  assert.deepEqual(updated.slice(0,initial.length).map(e=>e.id),initial.map(e=>e.id));
  assert.deepEqual(updated.map(e=>e.id),['z','a','b','00','0']);
  assert.equal(updated[1].description,'refreshed evidence');
  assert.deepEqual(mergeActivities([...updated].reverse()),updated); // Refresh/replay completion retains order.
});

test('oldest-first pagination appends pages and follows new events across the page boundary', async () => {
  let rows=Array.from({length:50},(_,i)=>({id:String(i+1).padStart(3,'0'),replay:true,video_timestamp_seconds:Math.floor(i/3),created_at:'2026-11-13T01:00:00Z'}));
  const calls=[];
  const backend=async query=>{
    calls.push(query);
    const ordered=query.order==='asc'?rows:[...rows].reverse();
    return {items:ordered.slice(query.offset,query.offset+query.limit),total:ordered.length};
  };
  const first=await readChronologicalActivityPages(backend);
  assert.equal(first.items.length,25);
  const second=await readChronologicalActivityPages(backend,{offset:first.nextOffset});
  const initial=mergeActivities([...first.items,...second.items]);
  assert.deepEqual(initial.map(e=>e.id),rows.map(e=>e.id));
  rows.push({id:'051',replay:true,video_timestamp_seconds:17,created_at:'2026-11-13T01:00:01Z'});
  const polled=await readChronologicalActivityPages(backend,{limit:50,followNewEvents:true});
  const refreshed=mergeActivities([...polled.items,polled.items[0]]);
  assert.deepEqual(refreshed.slice(0,50),initial);
  assert.equal(refreshed.at(-1).id,'051');
  assert.equal(refreshed.length,51);
  assert.ok(calls.every(query=>query.order==='asc'));
  assert.ok(calls.some(query=>query.offset===50));
});
