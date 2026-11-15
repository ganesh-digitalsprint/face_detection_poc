import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createAlertAuthority, authorityErrorMessage } from './alertAuthority.js';
const notFound=()=>Object.assign(new Error('Not found'),{response:{status:404}});
const row={id:'local-id',source_event_id:'source-event',row_version:4,status:'OPEN',allowed_actions:['ACKNOWLEDGED','RESOLVED','DISMISSED']};
const alert={id:'different-common-id',sourceEventId:'source-event',useCase:'grill_gate',rowVersion:1};

test('older Grill backend resolves snapshot local ID, verifies source identity and keeps the source version',async()=>{
 const calls=[];
 const authority=createAlertAuthority({grillGet:async()=>{throw notFound();},grillById:async(id)=>{calls.push(id);return row;}});
 const loaded=await authority.load({...alert,evidenceRefs:[{retrieval_path:'/api/v1/grill-gate/alerts/local-id/evidence/snapshot?video_job_id=video'}]});
 assert.deepEqual(calls,['local-id']);assert.equal(loaded.sourceApiId,'local-id');assert.equal(loaded.sourceRowVersion,4);assert.equal(loaded.id,'different-common-id');
});
test('without a snapshot, persisted video alerts supply a hint followed by an authoritative detail read',async()=>{
 const calls=[];
 const authority=createAlertAuthority({grillGet:async()=>{throw notFound();},grillVideo:async(id)=>{calls.push(['video',id]);return{alerts:[row]};},grillById:async(id)=>{calls.push(['detail',id]);return row;}});
 assert.equal((await authority.load({...alert,videoJobId:'video'})).sourceApiId,'local-id');
 assert.deepEqual(calls,[['video','video'],['detail','local-id']]);
});
test('legacy live lookup searches active then paginated persisted history',async()=>{
 const offsets=[];
 const authority=createAlertAuthority({grillGet:async()=>{throw notFound();},grillActive:async()=>({items:[]}),grillHistory:async(id,{offset})=>{offsets.push(offset);return offset===0?{items:[],next_offset:100}:{items:[row]};},grillById:async()=>row});
 assert.equal((await authority.load({...alert,assignmentId:'assignment'})).sourceApiId,'local-id');assert.deepEqual(offsets,[0,100]);
});
test('an unrelated snapshot hint cannot authorize an action on another source record',async()=>{
 const authority=createAlertAuthority({grillGet:async()=>{throw notFound();},grillById:async()=>({...row,source_event_id:'someone-else'})});
 await assert.rejects(authority.load({...alert,localId:'unrelated'}),error=>error.response.status===404);
});
for(const status of [401,403,500])test(`HTTP ${status} is not hidden by the compatibility lookup`,async()=>{
 let fallback=false;const failure={response:{status}};
 const authority=createAlertAuthority({grillGet:async()=>{throw failure;},grillById:async()=>{fallback=true;return row;}});
 await assert.rejects(authority.load({...alert,localId:'local-id'}),error=>error===failure);assert.equal(fallback,false);
});
test('mismatched and unversioned source responses remain read-only',async()=>{
 for(const invalid of [{...row,source_event_id:'wrong'}, {...row,row_version:undefined}]) {
  const authority=createAlertAuthority({grillGet:async()=>invalid});await assert.rejects(authority.load(alert),/invalid or mismatched/);
 }
});
test('terminal statuses cannot run stale lifecycle actions',async()=>{
 const authority=createAlertAuthority({grillAct:()=>assert.fail('must not mutate')});
 for(const status of ['RESOLVED','DISMISSED'])await assert.rejects(authority.transition({...alert,status,sourceAllowedActions:['RESOLVED'],sourceApiId:'local-id',sourceRowVersion:4},'RESOLVED',{note:'Reviewed'}),/not allowed/);
});
test('source authorization failures and missing rows have actionable error messages',()=>{
 assert.match(authorityErrorMessage({response:{status:401}}),/operator key/);
 assert.match(authorityErrorMessage(notFound()),/same persisted data/);
});
