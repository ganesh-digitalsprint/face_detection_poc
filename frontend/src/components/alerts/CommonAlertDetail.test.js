import assert from 'node:assert/strict';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

const baseAlert = (changes = {}) => ({id:'common-1',sourceEventId:'source-1',useCase:'branch_exterior',
  title:'Movement at Video 98366',summary:'Unusual movement for track #3',status:'OPEN',severity:'WARNING',
  occurredAt:'2026-11-16T08:27:50Z',cameraId:'camera-1',cameraName:'Video 98366',
  branchId:'branch-1',branchCode:'P001',branchName:'Central',placeName:'Pune',regionName:'West',branchManager:'A. Manager',
  zoneName:'Whole scene',resourceRefs:{zone_name:'Whole scene'},domainData:{confidence:0.63,track_ids:[3]},
  evidenceRefs:[],evidenceSnapshots:[],evidenceStatus:'UNAVAILABLE',evidenceUnavailableReason:'not_suspicious',
  allowedActions:[],...changes});

async function render(alert) {
  const server = await createServer({root:process.cwd(),server:{middlewareMode:true},appType:'custom',logLevel:'silent'});
  try {
    const {default: Component} = await server.ssrLoadModule('/src/components/alerts/CommonAlertDetail.jsx');
    return renderToStaticMarkup(React.createElement(Component,{alert,audit:{rows:[],loading:false,error:''},
      actionsEnabled:false,pending:false,notice:'',onAction:()=>{},onClose:()=>{}}));
  } finally { await server.close(); }
}

test('Branch details keep geographic place separate and explain intentionally excluded evidence',async()=>{
  const html=await render(baseAlert());
  assert.match(html,/Place<\/dt><dd>Pune/);
  assert.match(html,/Zone<\/dt><dd>Whole scene/);
  assert.match(html,/Confidence<\/dt><dd>63\.0%/);
  assert.match(html,/Track ID<\/dt><dd>3/);
  assert.match(html,/did not meet the evidence severity policy/);
  assert.doesNotMatch(html,/role="tab"[^>]*>Video clip/);
  assert.match(html,/Download snapshot<\/button>/);
});

test('snapshot and clip controls appear only for verified evidence URLs',async()=>{
  const html=await render(baseAlert({evidenceStatus:'CAPTURED',evidenceRefs:[
    {id:'snapshot-1',type:'snapshot',url:'http://source/snapshot.jpg'},
    {id:'clip-1',type:'clip',url:'http://source/clip.mp4'}],
    evidenceSnapshots:[{ref:{id:'snapshot-1',type:'snapshot'},url:'http://source/snapshot.jpg'}]}));
  assert.match(html,/role="tab"[^>]*>Video clip/);
  assert.match(html,/role="tab"[^>]*>Snapshots/);
  assert.match(html,/Download clip<\/a>/);
  assert.match(html,/Download snapshot<\/a>/);
});
