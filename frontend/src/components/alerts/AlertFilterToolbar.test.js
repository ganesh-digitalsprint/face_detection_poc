import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';

test('Alert Center branch choices come from the branch registry, independent of global selection', async () => {
  const server = await createServer({ root: process.cwd(), server:{ middlewareMode:true }, appType:'custom', logLevel:'silent' });
  try {
    const { availableBranchOptions } = await server.ssrLoadModule('/src/components/alerts/AlertFilterToolbar.jsx');
    const rows = [{ id:'branch-1', name:'Central' }, { id:'branch-2', name:'Airport' }];
    assert.deepEqual(availableBranchOptions(rows), rows);
    assert.deepEqual(availableBranchOptions(rows).map((row) => row.id), ['branch-1', 'branch-2']);
  } finally { await server.close(); }
});
