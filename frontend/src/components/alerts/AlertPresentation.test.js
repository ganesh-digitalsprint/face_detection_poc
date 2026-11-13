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
    const { default: LocalAlerts } = await server.ssrLoadModule('/src/use-cases/grill-gate/components/GrillGateAlerts.jsx');
    const localPage=renderToStaticMarkup(createElement(MemoryRouter,{ initialEntries:['/grill-gate?status=HISTORY'] },createElement(LocalAlerts,{assignmentId:'gate-1'})));
    assert.match(localPage,/Alert History/);assert.match(localPage,/Loading alerts/);
    const { default: AlertCenter, ServiceAlertDetail } = await server.ssrLoadModule('/src/pages/AlertCenter.jsx');
    const center=renderToStaticMarkup(createElement(MemoryRouter,{initialEntries:['/alerts/all?use_case=grill_gate']},createElement(AlertCenter)));
    for (const text of ['Grill Gate Monitoring','Active','History','Filter by evidence','Alert Center']) assert.ok(center.includes(text),text);
    const videoAlert={...alert,videoJobId:'video-source-1',domainData:{...alert.domainData,video_time_seconds:19.7,gate_open_duration_seconds:336.341}};
    const commonDetail=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(ServiceAlertDetail,{alert:videoAlert,audit:{rows:[],loading:false,error:''},actionsEnabled:true,onClose:()=>{}})));
    for (const text of ['HIGH','ACKNOWLEDGED','video-source-1','336.341','19.7','Occurred','No captured snapshot is attached']) assert.ok(commonDetail.includes(text),text);
    assert.doesNotMatch(commonDetail,/>Acknowledge</);

    const commented = {...videoAlert, acknowledgementComment:'Checked the captured snapshot', acknowledgedAt:'2026-11-12T01:00:00Z', acknowledgedBy:'reviewer'};
    const commonComment=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(ServiceAlertDetail,{alert:commented,audit:{rows:[],loading:false,error:''},actionsEnabled:true})));
    const sourceComment=renderToStaticMarkup(createElement(MemoryRouter,null,createElement(SourceAlertDetail,{alert:commented})));
    assert.match(commonComment,/Checked the captured snapshot/); assert.match(sourceComment,/Checked the captured snapshot/);
    assert.match(sourceComment,/reviewer/);
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
      for (const label of ['Acknowledge','Resolve','Discard']) assert.equal(common.includes(`>${label}</button>`), expected.includes(label),`Common ${status} ${label}`);
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
