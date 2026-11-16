import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';

test('Branch Exterior keeps the Live alert ticker and removes its floating popup presentation', async () => {
  const oldStorage = globalThis.localStorage;
  globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  const server = await createServer({ root: process.cwd(), server:{ middlewareMode:true }, appType:'custom', logLevel:'silent' });
  try {
    const { default: LiveMonitoringPage } = await server.ssrLoadModule('/src/use-cases/branch-exterior/pages/LiveMonitoringPage.jsx');
    const { default: BxLayout } = await server.ssrLoadModule('/src/use-cases/branch-exterior/components/BxLayout.jsx');
    const page = renderToStaticMarkup(createElement(MemoryRouter, null, createElement(LiveMonitoringPage)));
    const layout = renderToStaticMarkup(createElement(MemoryRouter, null, createElement(BxLayout, null, createElement('p', null, 'Branch content'))));
    assert.match(page, /Live alert ticker/);
    assert.match(page, /Waiting for events/);
    assert.match(layout, /Branch content/);
    assert.doesNotMatch(layout, /bx-toast-root|bx-toast/);
  } finally {
    await server.close();
    if (oldStorage === undefined) delete globalThis.localStorage; else globalThis.localStorage = oldStorage;
  }
});

test('Branch Exterior source details show canonical metadata, evidence controls, and a distinct zone', async () => {
  const server = await createServer({ root: process.cwd(), server:{ middlewareMode:true }, appType:'custom', logLevel:'silent' });
  try {
    const { default: Detail } = await server.ssrLoadModule('/src/use-cases/branch-exterior/components/BranchExteriorEventDetail.jsx');
    const event = { id:'source-1', camera_id:'camera-1', camera_name:'Front door', scenario:'loitering', severity:'high',
      confidence:0.92, track_ids:[4], created_at:'2026-11-16T10:00:00Z', message:'Person remained in the zone.',
      zone_name:'Entrance zone', status:'open', snapshot_path:'snapshots/front.jpg', clip_path:'clips/front.mp4',
      meta:{ branch_id:'branch-1', branch_code:'B001', branch_name:'Old Goa', place_name:'Panaji', region_name:'West', branch_manager:'Manager A' } };
    const html = renderToStaticMarkup(createElement(MemoryRouter, null,
      createElement(Detail, { id:event.id, initialEvent:event, incident:{ status:'OPEN' }, onClose:()=>{} })));
    for (const value of ['Front door','camera-1','Old Goa','B001','Panaji','West','Manager A','Entrance zone','loitering','92.0%','Track ID','Download snapshot','Download clip']) assert.ok(html.includes(value), value);
    assert.match(html, /storage\/snapshots\/front.jpg/);
    assert.match(html, /storage\/clips\/front.mp4/);
    assert.match(html, /<video[^>]*preload="metadata"/);
    assert.doesNotMatch(html, /<video[^>]*controls/);
    assert.match(html, /Checking video clip/);
  } finally { await server.close(); }
});

test('ticker cards render a saved snapshot and keep the camera placeholder when snapshot data is absent', async () => {
  const server = await createServer({ root: process.cwd(), server:{ middlewareMode:true }, appType:'custom', logLevel:'silent' });
  try {
    const { default: SourceIncidentCard } = await server.ssrLoadModule('/src/components/alerts/SourceIncidentCard.jsx');
    const saved = renderToStaticMarkup(createElement(MemoryRouter, null, createElement(SourceIncidentCard, {
      event:{ id:'source-1', camera_name:'Front', severity:'high', message:'Loitering', status:'open', snapshot_path:'snapshots/front.jpg' },
      useCase:'branch_exterior', thumbnailUrl:'http://localhost:8011/storage/snapshots/front.jpg', onSelect:()=>{},
    })));
    const missing = renderToStaticMarkup(createElement(MemoryRouter, null, createElement(SourceIncidentCard, {
      event:{ id:'source-2', camera_name:'Rear', severity:'medium', message:'Running', status:'open', snapshot_path:'' },
      useCase:'branch_exterior', onSelect:()=>{},
    })));
    assert.match(saved, /src="http:\/\/localhost:8011\/storage\/snapshots\/front.jpg"/);
    assert.match(missing, /No captured snapshot/);
    assert.doesNotMatch(missing, /<img/);
  } finally { await server.close(); }
});

test('Branch source details keep downloads disabled and explain policy exclusions when evidence was not captured', async () => {
  const server = await createServer({ root: process.cwd(), server:{ middlewareMode:true }, appType:'custom', logLevel:'silent' });
  try {
    const { default: Detail } = await server.ssrLoadModule('/src/use-cases/branch-exterior/components/BranchExteriorEventDetail.jsx');
    const html = renderToStaticMarkup(createElement(MemoryRouter, null, createElement(Detail, {
      id:'source-2', initialEvent:{ id:'source-2', camera_name:'Video 99346', status:'open', meta:{ evidence:'not_saved:not_suspicious' } }, onClose:()=>{},
    })));
    assert.match(html, /did not meet the evidence severity policy/);
    assert.match(html, /Download snapshot<\/button>/);
    assert.match(html, /Download clip<\/button>/);
    assert.doesNotMatch(html, /<a[^>]+Download (snapshot|clip)/);
  } finally { await server.close(); }
});
