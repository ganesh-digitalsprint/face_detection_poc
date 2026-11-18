import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';
import { normalizeGrillGateAlert } from '../../api/alertServiceModel.js';

// Use Vite's existing JSX transform instead of introducing a second test build tool.
test('shared cards and detail render real metadata, source links, and unavailable evidence', async () => {
  const server = await createServer({ root: process.cwd(), server:{ middlewareMode:true },appType:'custom',logLevel:'silent' });
  try {
    const { AlertCard, SourceAlertDetail } = await server.ssrLoadModule('/src/components/alerts/AlertPresentation.jsx');
    const alert=normalizeGrillGateAlert({ id:'local-42',source_event_id:'stable-42',use_case:'grill_gate',title:'Mesh occupancy limit exceeded',source_event_type:'MESH_OCCUPANCY_LIMIT_EXCEEDED',status:'ACKNOWLEDGED',severity:'HIGH',occurred_at:'2026-11-11T14:02:18Z',summary:'Six people observed',resource_refs:{ assignment_id:'gate-1',camera_id:'cam-1' },domain_data:{ observed_occupancy:6,maximum_occupancy:3,evidence_status:'UNAVAILABLE' },evidence_refs:[] });
    const card=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(AlertCard,{ alert,onSelect:()=>{} })));
    assert.match(card,/Six people observed/); assert.doesNotMatch(card, /Mesh occupancy limit exceeded|Grill Gate Monitoring|cam-1|2026/); assert.match(card,/ACKNOWLEDGED/); assert.match(card,/Open alert details/); assert.match(card,/No captured snapshot is attached/);
    const detail=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(SourceAlertDetail,{alert,onClose:()=>{}})));
    for (const text of ['Six people observed','People in mesh area','Maximum mesh occupancy','local-42','stable-42','Grill Gate Monitoring']) assert.ok(detail.includes(text),text);
    assert.match(detail,/assignment=gate-1/); assert.match(detail,/source_event_id=stable-42/);
    assert.doesNotMatch(detail,/Before|After|2.4 MB|2560/);
    const attributed = normalizeGrillGateAlert({id:'gate-branch-1',source_event_id:'gate-source-1',use_case:'grill_gate',
      source_event_type:'GATE_OPEN_TOO_LONG',title:'Gate remained open',status:'OPEN',severity:'WARNING',
      occurred_at:'2026-11-18T08:32:45Z',summary:'Gate exceeded open threshold',branch_id:'branch-1',camera_id:'cam-1',
      branch_name:'old goa',branch_code:'C99127-02',place_name:'goa',region_name:'south west',branch_manager:'Ganesh',
      camera_name:'Gate camera',source_type:'rtsp',video_job_id:'job-1',
      domain_data:{gate_state:'FULLY_OPEN',gate_open_duration_seconds:3.136,configured_threshold_seconds:3,video_time_seconds:7.04},
      evidence_refs:[{id:'snap-1',type:'snapshot',captured_at:'2026-11-18T08:32:48Z',retrieval_path:'/api/v1/grill-gate/alerts/gate-source-1/evidence/snap-1?video_job_id=job-1'}]});
    const detailActions=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(SourceAlertDetail,{alert:attributed,onClose:()=>{}},
      createElement('div',null,...['Acknowledge','Resolve','Discard'].map((label)=>createElement('button',{key:label,type:'button'},label))))));
    for (const text of ['Gate camera','cam-1','CCTV','old goa','C99127-02','goa','south west','Ganesh',
      'FULLY_OPEN','3.136 s','3 s','7.04 s','Occurred','GATE_OPEN_TOO_LONG','gate-branch-1','gate-source-1',
      'Snapshot captured at','Acknowledge','Resolve','Discard','Open Alert Center']) assert.ok(detailActions.includes(text),text);
    const noCamera=normalizeGrillGateAlert({id:'gate-upload',use_case:'grill_gate',video_job_id:'job-2',source_type:'uploaded_video',resource_refs:{video_job_id:'job-2'},domain_data:{}});
    const noCameraMarkup=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(SourceAlertDetail,{alert:noCamera})));
    assert.match(noCameraMarkup,/Camera name[\s\S]*?Uploaded video/);
    assert.match(noCameraMarkup,/Branch[\s\S]*?Not assigned/);
    assert.doesNotMatch(noCameraMarkup,/Camera ID|Branch code|Branch manager/);
    const { default: LocalAlerts } = await server.ssrLoadModule('/src/use-cases/grill-gate/components/GrillGateAlerts.jsx');
    const localPage=renderToStaticMarkup(createElement(MemoryRouter,{ initialEntries:['/grill-gate?status=HISTORY'] },createElement(LocalAlerts,{assignmentId:'gate-1'})));
    assert.match(localPage,/Alert History/);assert.match(localPage,/Loading alerts/);
    const { default: AlertCenter, ServiceAlertDetail } = await server.ssrLoadModule('/src/pages/AlertCenter.jsx');
    const center=renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/alerts?use_case=grill_gate']},createElement(AlertCenter)));
    for (const text of ['Grill Gate Monitoring','Active','History','Filter by evidence','Alert Center']) assert.ok(center.includes(text),text);
    const videoAlert={...alert,videoJobId:'video-source-1',domainData:{...alert.domainData,video_time_seconds:19.7,gate_open_duration_seconds:336.341}};
    const commonDetail=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(ServiceAlertDetail,{alert:videoAlert,audit:{rows:[],loading:false,error:''},actionsEnabled:true,onClose:()=>{}})));
    for (const text of ['HIGH','ACKNOWLEDGED','video-source-1','336.341','19.7','Occurred','No captured snapshot is attached']) assert.ok(commonDetail.includes(text),text);
    assert.match(commonDetail, /data-action="ACKNOWLEDGED" disabled/);

    const commented = {...videoAlert, acknowledgementComment:'Checked the captured snapshot', acknowledgedAt:'2026-11-12T01:00:00Z', acknowledgedBy:'reviewer'};
    const commonComment=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(ServiceAlertDetail,{alert:commented,audit:{rows:[],loading:false,error:''},actionsEnabled:true})));
    const sourceComment=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(SourceAlertDetail,{alert:commented})));
    assert.match(commonComment,/Checked the captured snapshot/); assert.match(sourceComment,/Checked the captured snapshot/);
    assert.match(sourceComment,/reviewer/);
    const pendingVault = renderToStaticMarkup(createElement(MemoryRouter,null,createElement(SourceAlertDetail,{
      alert:{...alert,id:'replay-local-id',sourceEventId:null,useCase:'vault_monitoring',
        displayAlertId:'Pending persistence',displaySourceEventId:'Pending persistence'}
    })));
    assert.equal((pendingVault.match(/Pending persistence/g) || []).length,2);
    assert.doesNotMatch(pendingVault,/source_event_id=|>replay-local-id</);
    const { default: CompactAlertCard } = await server.ssrLoadModule('/src/components/alerts/CompactAlertCard.jsx');
    for (const severity of ['WARNING', 'HIGH', 'CRITICAL', 'INFO']) {
      const markup = renderToStaticMarkup(createElement(CompactAlertCard, {
        alert: {...alert, severity, summary:'Gate remained open for 3.003 seconds.'},
        thumbnailUrl:'/storage/actual-snapshot.jpg', onSelect:()=>{},
      }));
      assert.match(markup, /src="\/storage\/actual-snapshot.jpg"/);
      assert.match(markup, /<strong[^>]*>3.003 seconds<\/strong>/);
      assert.match(markup, /rounded-\[20px\]/);
      assert.match(markup, new RegExp(severity));
      assert.equal((markup.match(/<button/g) || []).length, 1, 'one accessible card button without nested controls');
    }
    const { default: VaultCard } = await server.ssrLoadModule('/src/use-cases/vault-monitoring/components/alerts/AlertCard.jsx');
    const vaultCard = renderToStaticMarkup(createElement(MemoryRouter,null,createElement(VaultCard, {
      alert:{id:'vault-1',title:'Count mismatch',type:'COUNT_MISMATCH',message:'1 people present, 2 required',severity:'WARNING',status:'OPEN',allowedActions:['acknowledge','resolve','dismiss']},
      thumbnailUrl:'/storage/vault.jpg', onAction:()=>{},
    })));
    for (const text of ['/storage/vault.jpg','Open alert details']) assert.ok(vaultCard.includes(text),text);
    assert.doesNotMatch(vaultCard, />Acknowledge<|>Resolve<|>Discard<|Count mismatch|people present, 2 required.*people present, 2 required/);
    for (const status of ['OPEN','ACKNOWLEDGED','RESOLVED','DISMISSED']) {
      const expected = status==='OPEN' ? ['Acknowledge','Resolve','Discard'] : status==='ACKNOWLEDGED' ? ['Resolve','Discard'] : [];
      const drawer = renderToStaticMarkup(createElement(MemoryRouter,null,createElement(VaultCard, {
        variant:'drawer', alert:{id:'vault-1',title:'Count mismatch',type:'COUNT_MISMATCH',message:'A persisted incident',severity:'WARNING',status,allowedActions:['acknowledge','resolve','dismiss'],cameraId:'browser',createdAt:'2026-11-12T01:00:00Z'},onAction:()=>{},
      })));
      for (const label of ['Acknowledge','Resolve','Discard']) assert.equal(drawer.includes(`>${label}</button>`), expected.includes(label),`${status} ${label}`);
      assert.match(drawer,/Camera \/ source/); assert.match(drawer,/browser/);
      const common = renderToStaticMarkup(createElement(MemoryRouter,null,createElement(ServiceAlertDetail, {
        alert:{...alert,status,sourceAllowedActions:['ACKNOWLEDGED','RESOLVED','DISMISSED']},audit:{rows:[],loading:false,error:''},actionsEnabled:true,onAction:()=>{},
      })));
      for (const [target,label] of [['ACKNOWLEDGED','Acknowledge'],['RESOLVED','Resolve'],['DISMISSED','Discard']]) {
        assert.match(common, new RegExp(`>${label}</button>`));
        assert.equal(new RegExp(`data-action="${target}" disabled`).test(common), !expected.includes(label), `Common ${status} ${label} permission`);
      }
    }
    const { default: Confirmation } = await server.ssrLoadModule('/src/components/alerts/LifecycleConfirmation.jsx');
    for (const [target,label] of [['ACKNOWLEDGED','Acknowledge'],['RESOLVED','Resolve'],['DISMISSED','Discard']]) {
      const confirmation=renderToStaticMarkup(createElement(Confirmation,{target,onConfirm:()=>{},onClose:()=>{}}));
      assert.match(confirmation,new RegExp(`${label} this alert`));
      assert.match(confirmation,/<textarea[^>]*required/);
      assert.match(confirmation,/Cancel/);
      assert.match(confirmation, target==='ACKNOWLEDGED' ? /Comment[\s\S]*textarea|remain in Active/ : /evidence will remain available/);
      if(target==='ACKNOWLEDGED') { assert.match(confirmation,/Comment/); assert.match(confirmation,/remain in Active/); }
      assert.match(confirmation, /type="submit" disabled/);
    }

  } finally { await server.close(); }
});
