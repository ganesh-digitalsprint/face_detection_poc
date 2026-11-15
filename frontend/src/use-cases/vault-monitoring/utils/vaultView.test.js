import assert from 'node:assert/strict';
import test from 'node:test';

import { vaultActiveBranchId } from './vaultView.js';

test('Vault uses only canonical branch scope IDs', () => {
  assert.equal(vaultActiveBranchId({ type: 'branch', id: 'branch-1', name: 'Koramangala' }), 'branch-1');
  assert.equal(vaultActiveBranchId({ type: 'city', id: 'city-1' }), null);
  assert.equal(vaultActiveBranchId({ type: 'zone', id: 'zone-1' }), null);
  assert.equal(vaultActiveBranchId(null), null);
});
