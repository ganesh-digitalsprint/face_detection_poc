import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createEvidenceResolver, matchesEvidence, removeUnavailableSnapshot, verifiedEvidence } from './alertEvidence.js';
import { alertSourceLink, normalizeServiceAlert } from './alertServiceModel.js';
import { faceMaskEventLink } from '../layouts/routes.js';
import { sourceMediaUrl } from './sourceThumbnail.js';

const gateRef={provider:'grill_gate',id:'snapshot',type:'snapshot',retrieval_path:'/api/v1/grill-gate/alerts/local/evidence/snapshot?assignment_id=assignment'};
function api() {
  return {vault:async()=>({primary_evidence_id:'snapshot',evidence_count:1}),
    vaultAccess:async()=>({items:[{id:'snapshot',url:'https://evidence.invalid/snapshot.jpg'}]}),
    gate:async()=>({source_event_id:'event',evidence_refs:[gateRef]}),
    gateSnapshot:async()=>new Blob(['image'],{type:'image/jpeg'}),blobPreview:async()=> 'data:image/jpeg;base64,cHJldmlldw==',
    branch:async()=>({snapshot_path:'screenshots/branch_exterior/snapshot.jpg',clip_path:''}),
    face:async()=>({snapshot_url:'/api/events/event/evidence/snapshot',clip_status:'ready'}),
    probeImage:async()=>true,probeClip:async()=>true};
}

for(const useCase of ['vault_monitoring','grill_gate','branch_exterior','face_mask']) {
  test(`${useCase}: accessible thumbnails, references, counts and filters agree`,async()=>{
    const row=await createEvidenceResolver(api())({useCase,sourceEventId:'event',evidenceStatus:'UNAVAILABLE',evidenceRefs:[]});
    assert.equal(row.evidenceStatus,'CAPTURED');assert.equal(row.snapshotCount,1);
    assert.equal(row.evidenceCount,1);assert.equal(row.evidenceRefs.length,1);
    assert.equal(row.evidenceSnapshots.length,1);assert.ok(row.thumbnailUrl);
    assert.ok(matchesEvidence(row,'CAPTURED'));assert.ok(!matchesEvidence(row,'UNAVAILABLE'));
  });
  test(`${useCase}: missing or expired media cannot count as available`,async()=>{
    const row=await createEvidenceResolver({...api(),probeImage:async()=>false})({useCase,sourceEventId:'event',evidenceStatus:'CAPTURED'});
    assert.equal(row.evidenceStatus,useCase==='branch_exterior'?'FAILED':'UNAVAILABLE');assert.equal(row.evidenceCount,0);
    assert.equal(row.thumbnailUrl,'');assert.deepEqual(row.evidenceRefs,[]);
    assert.ok(!matchesEvidence(row,'CAPTURED'));
    assert.ok(matchesEvidence(row,useCase==='branch_exterior'?'FAILED':'UNAVAILABLE'));
  });
}

test('clip-only events do not enter the snapshot filter or unavailable count',async()=>{
  const result=await createEvidenceResolver({...api(),branch:async()=>({clip_path:'clips/branch_exterior/clip.mp4'})})({useCase:'branch_exterior',sourceEventId:'event'});
  assert.equal(result.evidenceStatus,'CAPTURED');assert.equal(result.clipCount,1);assert.equal(result.snapshotCount,0);
  assert.ok(!matchesEvidence(result,'CAPTURED'));assert.ok(!matchesEvidence(result,'UNAVAILABLE'));
});
test('a failed displayed image immediately removes only its availability and counts',()=>{
  const snapshot={id:'snapshot',type:'snapshot'},clip={id:'clip',type:'clip'};
  const row=verifiedEvidence([snapshot,clip],[{ref:snapshot,url:'image'}]);
  const failed=removeUnavailableSnapshot(row,'image');
  assert.equal(failed.snapshotCount,0);assert.equal(failed.clipCount,1);assert.equal(failed.evidenceCount,1);
  assert.equal(failed.thumbnailUrl,'');assert.ok(!matchesEvidence(failed,'CAPTURED'));
  assert.equal(removeUnavailableSnapshot(failed,'stale image'),failed);
});
test('source outages and malformed media do not break rendering',async()=>{
  const result=await createEvidenceResolver({...api(),branch:async()=>{throw new Error('offline');}})({useCase:'branch_exterior',sourceEventId:'event'});
  assert.equal(result.evidenceStatus,'FAILED');assert.equal(result.evidenceUnavailableReason,'evidence_retrieval_failed');assert.equal(result.snapshotCount,0);
  const gate=await createEvidenceResolver({...api(),gateSnapshot:async()=>new Blob(['html'],{type:'text/html'})})({useCase:'grill_gate',sourceEventId:'event'});
  assert.equal(gate.evidenceStatus,'UNAVAILABLE');
});
test('Branch Exterior policy exclusion and capture failure keep distinct evidence states',async()=>{
  const base={useCase:'branch_exterior',sourceEventId:'event'};
  const excluded=await createEvidenceResolver({...api(),branch:async()=>({snapshot_path:'',clip_path:'',meta:{evidence:'not_saved:not_suspicious'}})})(base);
  assert.equal(excluded.evidenceStatus,'UNAVAILABLE');
  assert.equal(excluded.evidenceUnavailableReason,'not_suspicious');
  const failed=await createEvidenceResolver({...api(),branch:async()=>({snapshot_path:'',clip_path:'',meta:{evidence:'failed:snapshot_write_failed'}})})(base);
  assert.equal(failed.evidenceStatus,'FAILED');
  assert.equal(failed.evidenceUnavailableReason,'snapshot_write_failed');
});
test('source access errors and mismatched Gate identities cannot expose unrelated evidence',async()=>{
  let fetched=false;
  const result=await createEvidenceResolver({...api(),gate:async()=>({source_event_id:'different',evidence_refs:[gateRef]}),
    gateSnapshot:async()=>{fetched=true;}})({useCase:'grill_gate',sourceEventId:'event'});
  assert.equal(result.evidenceStatus,'UNAVAILABLE');assert.equal(fetched,false);
});
test('pending clips remain pending and per-evidence access errors exclude only missing snapshots',async()=>{
  const pending=await createEvidenceResolver({...api(),face:async()=>({clip_status:'pending'})})({useCase:'face_mask',sourceEventId:'event'});
  assert.equal(pending.evidenceStatus,'PENDING');assert.equal(pending.evidenceCount,0);
  const partial=await createEvidenceResolver({...api(),vault:async()=>({evidence_refs:[{id:'missing',type:'snapshot'},{id:'snapshot',type:'snapshot'}],evidence_count:2})})({useCase:'vault_monitoring',sourceEventId:'event'});
  assert.equal(partial.snapshotCount,1);assert.equal(partial.evidenceRefs[0].id,'snapshot');
});
test('source navigation opens monitoring pages while centralized deep links remain available',()=>{
  assert.equal(alertSourceLink({useCase:'face_mask',sourceEventId:'id /?#'}),'/face-mask/events/id%20%2F%3F%23');
  assert.equal(faceMaskEventLink('id /?#'),'/alerts?source_event_id=id%20%2F%3F%23');
  assert.equal(alertSourceLink({useCase:'vault_monitoring'}),'/vault-access');
  assert.equal(alertSourceLink({useCase:'vault_monitoring',sourceType:'uploaded_video'}),'/vault-access?view=room&source=upload');
  assert.equal(alertSourceLink({useCase:'branch_exterior'}),'/branch-exterior/live');
  assert.equal(alertSourceLink({useCase:'grill_gate',sourceEventId:'event',assignmentId:'assignment'}),'/grill-gate?view=live&assignment=assignment&alert=event');
});
test('current and legacy paths use existing static media mounts without escaping source storage',()=>{
  assert.equal(sourceMediaUrl('http://source','screenshots/face_mask/photo.jpg','face_mask'),'http://source/storage/snapshots/photo.jpg');
  assert.equal(sourceMediaUrl('http://source','clips/branch_exterior/video.mp4','branch_exterior'),'http://source/storage/clips/video.mp4');
  assert.equal(sourceMediaUrl('http://source','snapshots/photo.jpg','face_mask'),'http://source/storage/snapshots/photo.jpg');
  assert.equal(sourceMediaUrl('http://source','snapshots/photo.jpg','branch_exterior'),'http://source/storage/snapshots/photo.jpg');
  assert.equal(sourceMediaUrl('http://source','screenshots/branch_exterior/photo.jpg','branch_exterior'),'http://source/storage/snapshots/photo.jpg');
  assert.equal(sourceMediaUrl('http://source','clips/incident.mp4','branch_exterior'),'http://source/storage/clips/incident.mp4');
  assert.equal(sourceMediaUrl('http://source','clips/branch_exterior/incident.mp4','branch_exterior'),'http://source/storage/clips/incident.mp4');
  assert.equal(sourceMediaUrl('http://source','../app.db','face_mask'),'');
  const row=normalizeServiceAlert({id:'a',use_case:'face_mask',evidence_refs:[{id:'snapshot',type:'snapshot'}],domain_data:{evidence_status:'UNAVAILABLE'}});
  assert.equal(row.evidenceStatus,'CAPTURED');assert.equal(row.snapshotCount,1);
});
