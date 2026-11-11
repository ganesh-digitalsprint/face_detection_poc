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
    assert.match(card,/Mesh occupancy limit exceeded/); assert.match(card,/ACKNOWLEDGED/); assert.match(card,/View details/); assert.match(card,/No captured snapshot is attached/);
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

  } finally { await server.close(); }
});
