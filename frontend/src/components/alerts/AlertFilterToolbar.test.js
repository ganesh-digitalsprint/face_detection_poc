import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';

test('Alert Center branch choices include registry branches and the canonical active branch once', async () => {
  const server = await createServer({ root: process.cwd(), server:{ middlewareMode:true }, appType:'custom', logLevel:'silent' });
  try {
    const { availableBranchOptions } = await server.ssrLoadModule('/src/components/alerts/AlertFilterToolbar.jsx');
    const rows = [{ id:'branch-1', name:'Central' }, { id:'branch-2', name:'Airport' }];
    assert.deepEqual(availableBranchOptions(rows, { type:'branch', id:'branch-1', name:'Central' }), rows);
    assert.deepEqual(availableBranchOptions(rows, { type:'branch', id:'branch-3', name:'MG Road' }).map((row) => row.id),
      ['branch-1', 'branch-2', 'branch-3']);
    assert.deepEqual(availableBranchOptions(rows, { type:'city', id:'city-1' }), rows);
  } finally { await server.close(); }
});
