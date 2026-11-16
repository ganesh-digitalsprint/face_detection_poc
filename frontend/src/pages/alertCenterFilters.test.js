import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clearAlertCenterFilters, updateAlertCenterQuery } from './alertCenterFilters.js';

test('branch filtering stores the canonical branch UUID and preserves unrelated deep-link filters', () => {
  const next = updateAlertCenterQuery('?alert_id=alert-1&use_case=branch_exterior&severity=HIGH', 'branch_id', 'branch-uuid-old-goa');
  assert.equal(next.get('branch_id'), 'branch-uuid-old-goa');
  assert.equal(next.get('alert_id'), 'alert-1');
  assert.equal(next.get('use_case'), 'branch_exterior');
  assert.equal(next.get('severity'), 'HIGH');
});

test('clearing the branch filter preserves alert deep links and does not restore a global selection', () => {
  const selected = updateAlertCenterQuery('?alert_id=alert-1&use_case=branch_exterior&branch_id=old-goa', 'branch_id', '');
  assert.equal(selected.has('branch_id'), false);
  assert.equal(selected.get('alert_id'), 'alert-1');
  assert.equal(selected.get('use_case'), 'branch_exterior');

  const allBranches = updateAlertCenterQuery(selected, 'branch_id', '');
  assert.equal(allBranches.has('branch_id'), false);
  assert.equal(allBranches.get('alert_id'), 'alert-1');
  assert.equal(allBranches.get('use_case'), 'branch_exterior');
});

test('changing Alert Center filters keeps the filter state independent and preserves unrelated parameters', () => {
  const history = updateAlertCenterQuery('?branch_id=branch-old-goa&alert_id=alert-1&use_case=branch_exterior', 'group', 'HISTORY');
  assert.equal(history.get('group'), 'HISTORY');
  assert.equal(history.get('branch_id'), 'branch-old-goa');
  const otherUseCase = updateAlertCenterQuery(history, 'use_case', 'vault_monitoring');
  assert.equal(otherUseCase.get('group'), 'HISTORY');
  assert.equal(otherUseCase.get('branch_id'), 'branch-old-goa');
  assert.equal(otherUseCase.get('alert_id'), 'alert-1');
});

test('Clear all removes filter parameters but preserves the selected alert detail', () => {
  const cleared = clearAlertCenterFilters('?alert_id=alert-1&source_event_id=event-1&branch_id=branch-1&use_case=branch_exterior');
  assert.equal(cleared.get('alert_id'), 'alert-1');
  assert.equal(cleared.has('branch_id'), false);
  assert.equal(cleared.has('source_event_id'), false);
});
