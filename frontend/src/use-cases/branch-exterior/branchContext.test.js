import assert from 'node:assert/strict';
import { test } from 'node:test';
import { branchIdBody, branchIdQuery, canonicalBranchId } from './branchContext.js';

test('Branch Exterior sessions carry only canonical branch scope IDs',()=>{
  const branch={type:'branch',id:'canonical-branch',name:'Old Goa'};
  assert.equal(canonicalBranchId(branch),'canonical-branch');
  assert.deepEqual(branchIdQuery(branch),{branch_id:'canonical-branch'});
  assert.deepEqual(branchIdBody(branch),{branch_id:'canonical-branch'});
  for(const scope of [{type:'city',id:'city-1'},{type:'zone',id:'zone-1'},null,{type:'branch',id:''}]) {
    assert.equal(canonicalBranchId(scope),null);
    assert.deepEqual(branchIdQuery(scope),{});
    assert.deepEqual(branchIdBody(scope),{});
  }
});
