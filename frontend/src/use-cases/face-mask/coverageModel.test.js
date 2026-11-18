import assert from 'node:assert/strict';
import test from 'node:test';
import { coverageLabel, coverageSeverity, coverageOfAlert, partialCount } from './coverageModel.js';

test('new states have labels and severities while legacy events retain their severity', () => {
  assert.equal(coverageLabel('PARTIALLY_COVERED'), 'Partial');
  assert.equal(coverageLabel('FULLY_COVERED'), 'Full');
  assert.equal(coverageLabel(null), 'Legacy / unknown');
  assert.equal(coverageSeverity({ coverage_state: 'PARTIALLY_COVERED', severity: 'HIGH' }), 'MEDIUM');
  assert.equal(coverageSeverity({ coverage_state: 'FULLY_COVERED' }), 'HIGH');
  assert.equal(coverageSeverity({ coverage_state: null, severity: 'HIGH' }), 'HIGH');
  assert.equal(coverageOfAlert({ domainData: { coverage_state: 'FULLY_COVERED' } }), 'FULLY_COVERED');
});

test('partial summary count stays unknown until the service reports it', () => {
  assert.equal(partialCount({ partially_covered: 0 }), 0);
  assert.equal(partialCount({ partial_count: 3 }), 3);
  assert.equal(partialCount({ concealed: 4 }), null);
});
