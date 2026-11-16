import test from 'node:test';
import assert from 'node:assert/strict';
import { blankBranch, validateBranch } from './branchValidation.js';

const valid = { ...blankBranch, name: 'Main branch', code: 'C99127-01', pincode: '560001', phone: '+919876543210', email: 'manager@example.com' };

test('branch form accepts complete valid details', () => {
  assert.deepEqual(validateBranch(valid, 'city-id'), {});
});

test('branch form validates location and editable details', () => {
  assert.ok(validateBranch({ ...valid, name: ' ' }, 'city-id').name);
  assert.ok(validateBranch(valid, '').city);
  assert.ok(validateBranch({ ...valid, code: '!bad' }, 'city-id').code);
  assert.ok(validateBranch({ ...valid, pincode: '123' }, 'city-id').pincode);
  assert.ok(validateBranch({ ...valid, phone: 'abc' }, 'city-id').phone);
  assert.ok(validateBranch({ ...valid, email: 'bad' }, 'city-id').email);
  assert.ok(validateBranch({ ...valid, timezone: 'Not/AZone' }, 'city-id').timezone);
});
