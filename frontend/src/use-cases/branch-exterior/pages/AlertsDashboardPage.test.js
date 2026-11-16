import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('Branch event preview renders retained evidence and a neutral missing fallback', async () => {
  const server = await createServer({ root: process.cwd(), server:{ middlewareMode:true }, appType:'custom', logLevel:'silent' });
  try {
    const { EventPreview } = await server.ssrLoadModule('/src/use-cases/branch-exterior/pages/AlertsDashboardPage.jsx');
    const retained = renderToStaticMarkup(createElement(EventPreview, { event:{ id:'event-1', camera_name:'Front', snapshot_path:'screenshots/branch_exterior/frame.jpg' }, onOpen:()=>{} }));
    assert.match(retained, /storage\/snapshots\/frame.jpg/);
    assert.match(retained, /Open evidence for Front/);
    assert.match(retained, /Captured evidence/);
    const missing = renderToStaticMarkup(createElement(EventPreview, { event:{ id:'event-2', camera_name:'Rear', snapshot_path:'' }, onOpen:()=>{} }));
    assert.match(missing, /No snapshot/);
    assert.doesNotMatch(missing, /<img/);
  } finally { await server.close(); }
});
