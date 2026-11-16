import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createAlertAuthority } from './alertAuthority.js';
import { availableActions,buildLifecycleBody } from './alertServiceModel.js';
import { sourceMediaUrl } from './sourceThumbnail.js';
import { sourceIncidentView } from '../components/alerts/sourceIncidentModel.js';

for(const useCase of ['grill_gate','vault_monitoring']) test(`${useCase}: Common commands use source identity, version and allowed actions`,async()=>{
  const calls=[];
  const raw={id:useCase==='vault_monitoring'?'stable-source':'source-row',source_event_id:'stable-source',row_version:7,source_event_version:12,status:'OPEN',allowed_actions:useCase==='grill_gate'?['ACKNOWLEDGED','RESOLVED','DISMISSED']:['acknowledge','resolve','dismiss'],evidence_refs:[{id:'snapshot'}]};
  const api={grillGet:async(id)=>{calls.push(['read',id]);return raw;},vaultGet:async(id)=>{calls.push(['read',id]);return raw;},
    grillAct:async(...args)=>{calls.push(args);return {...raw,status:'RESOLVED',row_version:8,source_event_version:13};},
    vaultAct:async(...args)=>{calls.push(args);return {...raw,status:'RESOLVED',row_version:8,source_event_version:13};},
    common:()=>{throw new Error('Competing writer must never be used');}};
  const authority=createAlertAuthority(api);
  const common={id:'common-row',sourceEventId:'stable-source',useCase,rowVersion:2,sourceEventVersion:1};
  const loaded=await authority.load(common);
  assert.deepEqual(calls[0],['read','stable-source']);
  assert.equal(availableActions(loaded,true).find((a)=>a.target==='DISMISSED').label,'Discard');
  const body=buildLifecycleBody(loaded,'RESOLVED','Reviewed footage');
  assert.equal(body.expected_version,7);
  const updated=await authority.transition(loaded,'RESOLVED',body);
  assert.equal(updated.id,'common-row');assert.equal(updated.status,'RESOLVED');assert.equal(updated.rowVersion,2);
  assert.deepEqual(updated.evidenceRefs,[{id:'snapshot'}]);assert.equal(updated.confirmedSourceVersion,13);
  assert.equal(calls[1][0],raw.id);
  await assert.rejects(authority.transition({...loaded,sourceAllowedActions:[]},'DISMISSED',body),/not allowed/);
});

test('Common remains the single incident writer for Branch Exterior',async()=>{
  for(const useCase of ['branch_exterior']) {
    let received;
    const api=createAlertAuthority({common:async(...args)=>{received=args;return{status:'DISMISSED'};}});
    const alert={id:'common-id',useCase,rowVersion:5,status:'OPEN',allowedActions:['DISMISSED']};
    assert.equal(await api.load(alert),alert);
    await api.transition(alert,'DISMISSED',{expected_version:5,note:'Reviewed'});
    assert.deepEqual(received,['common-id','DISMISSED',{expected_version:5,note:'Reviewed'}]);
  }
});

test('Face Mask lifecycle actions use source review transitions and versions',async()=>{
  const calls=[];
  let row={id:'face-event',status:'OPEN',review_version:1,score:.91,covering_type:'scarf',track_id:7};
  const api=createAlertAuthority({
    faceGet:async()=>row,
    faceReview:async(id,to,note,version)=>{calls.push(['review',id,to,note,version]);row={...row,status:to,review_version:version+1};return row;},
    faceClose:async(id,note,version)=>{calls.push(['close',id,note,version]);row={...row,status:'CLOSED',review_version:version+1};return row;},
  });
  let alert=await api.load({id:'common',sourceEventId:'face-event',useCase:'face_mask',domainData:{}});
  assert.deepEqual(availableActions(alert,true).map((item)=>item.target),['ACKNOWLEDGED','RESOLVED','DISMISSED']);
  alert=await api.transition(alert,'RESOLVED',{note:'Confirmed and handled'});
  assert.deepEqual(calls,[['review','face-event','UNDER_REVIEW','Confirmed and handled',1],
    ['review','face-event','CONFIRMED','Confirmed and handled',2],['close','face-event','Confirmed and handled',3]]);
  assert.equal(alert.status,'RESOLVED');
});

test('source media URLs remain on the expected service storage path',()=>{
  assert.equal(sourceMediaUrl('http://branch','snapshots/a b.jpg'),'http://branch/storage/snapshots/a%20b.jpg');
  for(const value of ['../secret.jpg','http://other/a.jpg','C:/secret.jpg','a\\b.jpg','/private.jpg','a?key=x']) assert.equal(sourceMediaUrl('http://branch',value),'');
});

test('source feeds display Common incident status without changing review records',()=>{
  const event={id:'event',status:'open',message:'Detection',severity:'high'};
  const common={id:'common',status:'DISMISSED'};
  assert.equal(sourceIncidentView(event,'branch_exterior',common),common);
  assert.equal(event.status,'open');
});


test('Grill acknowledgement sends the comment with the authoritative ID and version', async()=>{
  let sent;
  const source={id:'local',source_event_id:'stable',row_version:4,status:'OPEN',allowed_actions:['ACKNOWLEDGED','RESOLVED','DISMISSED']};
  const authority=createAlertAuthority({grillGet:async()=>source,grillAct:async(...args)=>{sent=args;return {...source,status:'ACKNOWLEDGED',row_version:5,acknowledgement_comment:args[3],acknowledged_at:'2026-11-12T01:00:00Z',acknowledged_by:'reviewer'};}});
  const alert=await authority.load({id:'common',sourceEventId:'stable',useCase:'grill_gate',rowVersion:1});
  const updated=await authority.transition(alert,'ACKNOWLEDGED',buildLifecycleBody(alert,'ACKNOWLEDGED','  Reviewed snapshot  '));
  assert.deepEqual(sent,['local','ACKNOWLEDGED',4,'Reviewed snapshot']);
  assert.equal(updated.id,'common'); assert.equal(updated.status,'ACKNOWLEDGED');
  assert.equal(updated.acknowledgementComment,'Reviewed snapshot'); assert.equal(updated.acknowledgedBy,'reviewer');
  assert.deepEqual(availableActions(updated,true).map((item)=>item.target),['RESOLVED','DISMISSED']);
});
