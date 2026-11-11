import assert from 'node:assert/strict';
import { test } from 'node:test';
import { normalizeServiceAlert, normalizeGrillGateAlert, grillEvidenceRequest, grillAlertMetadata,
  alertSourceLink, evidenceLabel, grillSnapshotRefs, availableActions, matchesStatus, mergeById } from './alertServiceModel.js';
import { statusGroupPage } from './alertStatusPage.js';
import { createGrillAlertApi } from '../use-cases/grill-gate/grillAlertFeed.js';

const record = (status = 'OPEN', more = {}) => ({ id: 'local-1', source_event_id: 'source-1', use_case: 'grill_gate',
  source_event_type: 'GATE_OPEN_TOO_LONG', severity: 'WARNING', status, title: 'Gate open without a completed crossing',
  row_version: 2, resource_refs: { video_job_id: 'video-1' }, domain_data: { gate_state: 'FULLY_OPEN', gate_open_duration_seconds: 5.2, configured_threshold_seconds: 4, evidence_status: 'CAPTURED', video_time_seconds: 19.7 },
  evidence_refs: [{ id: 'snapshot-1', type: 'snapshot', retrieval_path: '/api/v1/grill-gate/alerts/local-1/evidence/snapshot-1?video_job_id=video-1' }], ...more });

test('local and published incidents share stable identity, evidence and metadata, with distinct storage IDs', () => {
  const local = normalizeGrillGateAlert(record());
  const common = normalizeServiceAlert(record('OPEN', { id: 'common-1' }));
  assert.equal(local.sourceEventId, common.sourceEventId);
  assert.equal(local.localId, 'local-1');
  assert.equal(common.localId, null);
  assert.deepEqual(local.evidenceRefs, common.evidenceRefs);
  assert.deepEqual(grillAlertMetadata(local), grillAlertMetadata(common));
  assert.equal(common.evidenceStatus, 'CAPTURED');
  assert.deepEqual(availableActions({ ...common, allowedActions: ['RESOLVED'] }, true), []);
});

test('all incident types, including unknown future types, retain backend metadata and zero counts', () => {
  for (const type of ['GATE_OPEN_TOO_LONG','GATE_PARTIALLY_OPEN_TOO_LONG','MESH_OCCUPANCY_LIMIT_EXCEEDED','FUTURE_ALERT']) {
    const view = normalizeGrillGateAlert(record('OPEN', { source_event_type: type, domain_data: { observed_occupancy: 0, maximum_occupancy: 3 } }));
    assert.equal(view.sourceEventType, type);
    assert.deepEqual(grillAlertMetadata(view), [['People in mesh area',0],['Maximum mesh occupancy',3]]);
  }
});

test('active and history are disjoint and cover every persisted lifecycle status', () => {
  for (const status of ['OPEN','ACKNOWLEDGED','RESOLVED','DISMISSED']) {
    const view = normalizeGrillGateAlert(record(status));
    assert.notEqual(matchesStatus(view,'ACTIVE'), matchesStatus(view,'HISTORY'));
    assert.equal(matchesStatus(view,'ACTIVE'), ['OPEN','ACKNOWLEDGED'].includes(status));
  }
});

test('source navigation preserves video/assignment, source event and terminal history', () => {
  const query = new URL(alertSourceLink(normalizeGrillGateAlert(record('RESOLVED'))),'http://test').searchParams;
  assert.equal(query.get('job'),'video-1'); assert.equal(query.get('alert'),'source-1'); assert.equal(query.get('status'),'HISTORY');
  const live = new URL(alertSourceLink(normalizeGrillGateAlert(record('OPEN',{ resource_refs: { assignment_id: 'live-1' } }))),'http://test');
  assert.equal(live.searchParams.get('assignment'),'live-1');
  assert.equal(live.searchParams.get('view'),'live');
  assert.equal(alertSourceLink({ useCase: 'branch_exterior' }),'/alerts/branch');
});

test('snapshot routes use exactly one source scope and reject hosts, traversal and unscoped references', () => {
  assert.deepEqual(grillEvidenceRequest(record().evidence_refs[0]), { path: '/api/v1/grill-gate/alerts/local-1/evidence/snapshot-1', params: { video_job_id: 'video-1' } });
  for (const path of ['https://host/api/v1/grill-gate/alerts/a/evidence/b?video_job_id=v','//host/api/v1/grill-gate/alerts/a/evidence/b','/api/v1/grill-gate/alerts/a/../../evil','/api/v1/grill-gate/alerts/a/evidence/b','/api/v1/grill-gate/alerts/a/evidence/b?assignment_id=a&video_job_id=v']) {
    assert.equal(grillEvidenceRequest({ retrieval_path: path }), null);
  }
});

test('republication deduplicates Grill Gate by source ID without merging Vault or Branch IDs', () => {
  const first = normalizeServiceAlert(record());
  const latest = { ...first, id: 'published-2', status: 'RESOLVED' };
  assert.deepEqual(mergeById([first],[latest],true),[latest]);
  assert.equal(mergeById([{ ...first, useCase:'branch_exterior', id:'b1' }],[{ ...first,useCase:'branch_exterior',id:'b2' }],true).length,2);
});

test('persisted video alerts survive empty monitoring, completion and adapter recreation after navigation', async () => {
  const api = { video: async () => ({ monitoring: null, items: [], alerts: [record(),record('RESOLVED',{ id:'local-2',source_event_id:'source-2' })] }) };
  for (let mount=0; mount<2; mount++) {
    const adapter = createGrillAlertApi({ jobId:'video-1',api });
    assert.equal((await adapter.list({ status:'ACTIVE' })).items[0].id,'local-1');
    assert.equal((await adapter.list({ status:'HISTORY' })).items[0].id,'local-2');
  }
});

test('missing or unavailable persisted video alert data rejects rather than clearing the list', async () => {
  for (const result of [{ monitoring:null },{ alerts:[], alerts_available:false }]) {
    const adapter = createGrillAlertApi({ jobId:'video-1',api:{ video:async()=>result } });
    await assert.rejects(adapter.list({ status:'ACTIVE' }));
  }
});

test('live history excludes acknowledged incidents and retains pagination and assignment scope', async () => {
  let received;
  const adapter = createGrillAlertApi({ assignmentId:'assignment-1',api:{ history:async (...args)=>{
    received=args; return { items:[record('ACKNOWLEDGED'),record('DISMISSED',{ id:'history',source_event_id:'h' })],next_offset:100 };
  } } });
  const page = await adapter.list({ status:'HISTORY',cursor:'0' });
  assert.equal(received[0],'assignment-1'); assert.equal(page.items.length,1); assert.equal(page.items[0].status,'DISMISSED'); assert.equal(page.nextCursor,'100');
});

for (const sort of ['newest','oldest']) test(`combined status pagination preserves global ${sort} ordering without omissions`, async () => {
  const datasets = { OPEN:[9,8,7,6,5], ACKNOWLEDGED:[10,4,3,2,1] };
  const fetchPage = async (params) => {
    assert.ok(['OPEN','ACKNOWLEDGED'].includes(params.status)); assert.equal(params.group,undefined);
    const values = [...datasets[params.status]].sort((a,b)=>sort==='newest'?b-a:a-b);
    const offset=Number(params.cursor || 0), batch=values.slice(offset,offset+2);
    return { items:batch.map((n)=>({ id:String(n),occurredAt:String(n).padStart(2,'0') })),hasMore:offset+2<values.length,nextCursor:String(offset+2) };
  };
  const ids=[]; let cursor;
  do {
    const page=await statusGroupPage(fetchPage,{ group:'ACTIVE',limit:3,sort,cursor });
    ids.push(...page.items.map((a)=>Number(a.id))); cursor=page.nextCursor;
  } while(cursor);
  assert.deepEqual(ids,sort==='newest'?[10,9,8,7,6,5,4,3,2,1]:[1,2,3,4,5,6,7,8,9,10]);
});


test('old incidents without references are not mistaken for a failed snapshot request',()=>{
  const view=normalizeGrillGateAlert(record('OPEN',{evidence_refs:[],domain_data:{}}));
  assert.deepEqual(view.evidenceRefs,[]);
  assert.equal(evidenceLabel(view),'No snapshot attached');
});

test('valid snapshot references are recognized without optional legacy evidence status',()=>{
  const view=normalizeServiceAlert(record('OPEN',{domain_data:{}}));
  assert.equal(view.evidenceStatus,'CAPTURED');
  assert.equal(evidenceLabel(view),'Snapshot captured');
  assert.equal(grillSnapshotRefs(view).length,1);
  const mixed={...view,evidenceRefs:[{type:'clip',id:'clip'},...view.evidenceRefs]};
  assert.equal(grillSnapshotRefs(mixed)[0].id,'snapshot-1');
});
