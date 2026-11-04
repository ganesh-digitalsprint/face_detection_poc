import assert from 'node:assert/strict';
import test from 'node:test';
import { filterZones, fromBranchZone, fromFaceMaskRoi, parseUseCase, ZONE_TYPES } from './regionsModel.js';

test('parseUseCase falls back to all for unknown values', () => {
  assert.equal(parseUseCase('face_mask'), 'face_mask');
  assert.equal(parseUseCase('nope'), 'all');
  assert.equal(parseUseCase(null), 'all');
});

test('Branch zones normalise to the common shape, always enabled', () => {
  const z = fromBranchZone({ id: 'z1', camera_id: 'c1', name: 'ATM', zone_type: 'atm', polygon: [[0, 0], [1, 0], [1, 1]] });
  assert.deepEqual(z, { id: 'z1', use_case: 'branch_exterior', camera_id: 'c1', name: 'ATM', zone_type: 'atm', points: 3, enabled: true, direction: false });
});

test('Face Mask ROIs normalise, keep enabled=false and default the type', () => {
  const z = fromFaceMaskRoi({ id: 'r1', camera_id: 'c9', name: 'Grill Gate', polygon: [{}, {}, {}, {}], inward_vector: { x: 0, y: -1 }, enabled: false });
  assert.equal(z.use_case, 'face_mask');
  assert.equal(z.zone_type, 'entry_roi');
  assert.equal(z.enabled, false);
  assert.equal(z.direction, true);
  assert.equal(z.points, 4);
});

test('filterZones keeps one use case, or everything for all', () => {
  const zones = [{ use_case: 'face_mask' }, { use_case: 'branch_exterior' }];
  assert.equal(filterZones(zones, 'all').length, 2);
  assert.deepEqual(filterZones(zones, 'face_mask'), [{ use_case: 'face_mask' }]);
});

test('zone type lists are use-case specific and Vault has none yet', () => {
  assert.deepEqual(ZONE_TYPES.face_mask, ['entry_roi']);
  assert.equal(ZONE_TYPES.vault_access.length, 0);
  assert.ok(ZONE_TYPES.branch_exterior.includes('restricted'));
});
