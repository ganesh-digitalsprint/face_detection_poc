import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createGrillAlertApi, videoAlertSession } from './grillAlertFeed.js';

const incident = (status='OPEN', version=1) => ({id:'incident-1',source_event_id:'source-1',video_job_id:'job-1',source_event_type:'GATE_OPEN_TOO_LONG',status,row_version:version,evidence_refs:[]});

test('gate changes, timer resets, empty monitoring and empty alert snapshots do not erase observed persisted records',async()=>{
  const responses=[{alerts:[incident()],monitoring:{gate_state:'FULLY_OPEN'}},{alerts:[],monitoring:{gate_state:'PARTIALLY_OPEN',open_without_crossing_seconds:0}},{alerts:[],monitoring:{gate_state:'CLOSED'}},{alerts:[],monitoring:null}];
  const feed=createGrillAlertApi({jobId:'job-1',api:{video:async()=>responses.shift()}});
  for(let i=0;i<4;i++) assert.equal((await feed.list({status:'ACTIVE'})).items[0].id,'incident-1');
  assert.equal(feed.count('ACTIVE'),1);
});

test('persisted resolution moves the same incident to History and never resurrects it on an omitted poll',async()=>{
  const responses=[{alerts:[incident()]},{alerts:[incident('RESOLVED',2)]},{alerts:[]}];
  const feed=createGrillAlertApi({jobId:'job-1',api:{video:async()=>responses.shift()}});
  assert.equal((await feed.list({status:'ACTIVE'})).items.length,1);
  assert.equal((await feed.list({status:'ACTIVE'})).items.length,0);
  const history=await feed.list({status:'HISTORY'});
  assert.equal(history.items[0].status,'RESOLVED');assert.equal(feed.count('HISTORY'),1);
});

test('omitted records reconcile persisted status using the authenticated detail read',async()=>{
  let iteration=0;
  const feed=createGrillAlertApi({jobId:'job-1',api:{video:async()=>({alerts:iteration++ ? [] : [incident()]}),detail:async(id)=>{assert.equal(id,'incident-1');return incident('DISMISSED',2);}}});
  await feed.list({status:'ACTIVE'});
  assert.equal((await feed.list({status:'ACTIVE'})).items.length,0);
  assert.equal((await feed.list({status:'HISTORY'})).items[0].status,'DISMISSED');
});

test('older persisted responses cannot undo a confirmed lifecycle action',async()=>{
  const feed=createGrillAlertApi({jobId:'job-1',api:{video:async()=>({alerts:[incident()]})}});
  await feed.list({status:'ACTIVE'});
  feed.applyUpdate({id:'incident-1',localId:'incident-1',sourceEventId:'source-1',status:'RESOLVED',rowVersion:2});
  assert.equal((await feed.list({status:'ACTIVE'})).items.length,0);
  assert.equal((await feed.list({status:'HISTORY'})).items[0].rowVersion,2);
});

test('a new processing job has an independent empty incident collection',async()=>{
  const first=createGrillAlertApi({jobId:'job-1',api:{video:async()=>({alerts:[incident()]})}});
  await first.list({status:'ACTIVE'});
  const second=createGrillAlertApi({jobId:'job-2',api:{video:async()=>({alerts:[]})}});
  assert.equal((await second.list({status:'ACTIVE'})).items.length,0);
  assert.equal(first.count('ACTIVE'),1);
});

test('aborted responses cannot populate an abandoned alert session',async()=>{
  const controller=new AbortController();
  const feed=createGrillAlertApi({jobId:'job-1',api:{video:async()=>{controller.abort();return{alerts:[incident()]};}}});
  await assert.rejects(feed.list({status:'ACTIVE'},controller.signal),{name:'AbortError'});
  assert.equal(feed.count('ACTIVE'),0);
});

test('uploading, queuing and loading a replacement preserve the session until processing begins',()=>{
  assert.equal(videoAlertSession('job-1',null),'job-1');
  for(const status of ['UPLOADED','QUEUED']) assert.equal(videoAlertSession('job-1',{job_id:'job-2',status}),'job-1');
  assert.equal(videoAlertSession('job-1',{job_id:'job-2',status:'PROCESSING'}),'job-2');
  assert.equal(videoAlertSession(null,{job_id:'job-2',status:'COMPLETED'}),'job-2');
  assert.equal(videoAlertSession('job-1',{job_id:'job-2',status:'FAILED'}),'job-1');
});
