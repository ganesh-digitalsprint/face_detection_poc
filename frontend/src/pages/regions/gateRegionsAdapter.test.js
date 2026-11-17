import assert from 'node:assert/strict';
import test from 'node:test';
import { createGateZoneWrites, loadGateZoneRows } from './gateRegionsAdapter.js';
import { parseUseCase, USE_CASES, ZONE_TYPES } from './regionsModel.js';

const zone = { id: 'z1', name: 'Approach', zone_type: 'gate_approach', polygon: [[0, 0], [1, 0], [0, 1]], enabled: false };
const mock = (overrides = {}) => ({
  listGrillGateAssignments: async () => [{ id: 'a1', camera_id: 'c1' }],
  listGrillGateCameras: async () => [{ id: 'c1', name: 'Gate camera' }],
  listGrillGateVideoJobs: async () => ({ items: [{ job_id: 'j1', filename: 'gate.mp4' }], total: 1 }),
  listAssignmentZones: async () => [zone],
  getVideoJobConfig: async () => ({ zones: [{ ...zone, id: 'v1' }] }),
  ...overrides,
});

test('Gate filter and deep link use the sidebar label', () => {
  assert.equal(parseUseCase('grill_gate'), 'grill_gate');
  assert.deepEqual(USE_CASES.map((row) => row.label), ['All', 'Vault Access', 'Branch Exterior', 'Gate Monitoring', 'Face Mask']);
  assert.deepEqual(ZONE_TYPES.grill_gate, ['gate_leaf_roi', 'gate_approach', 'gate_interior', 'mesh_area']);
});

test('adapter lists live and video zones with stable source IDs and disabled state', async () => {
  const result = await loadGateZoneRows(mock());
  assert.equal(result.partialError, '');
  assert.equal(result.rows.length, 2);
  assert.deepEqual(result.rows.map((row) => [row.source_kind, row.camera, row.points, row.enabled]), [
    ['live', 'Gate camera', 3, false], ['video', 'gate.mp4', 3, false],
  ]);
  assert.equal(result.rows[0].assignment_id, 'a1');
  assert.equal(result.rows[1].job_id, 'j1');
});

test('one failed source leaves other Gate rows available', async () => {
  const result = await loadGateZoneRows(mock({ getVideoJobConfig: async () => { throw new Error('offline'); } }));
  assert.equal(result.rows.length, 1);
  assert.match(result.partialError, /1 Gate source/);
});

test('video-list failure does not hide live camera zones', async () => {
  const result = await loadGateZoneRows(mock({ listGrillGateVideoJobs: async () => { throw new Error('videos offline'); } }));
  assert.equal(result.rows.length, 1);
  assert.equal(result.rows[0].camera, 'Gate camera');
  assert.match(result.partialError, /1 Gate source/);
});

test('writes delegate to the existing Gate APIs including toggle and delete', async () => {
  const calls = [];
  const api = {
    createAssignmentZone: async (...args) => calls.push(['create', ...args]),
    updateAssignmentZone: async (...args) => calls.push(['update', ...args]),
    deleteAssignmentZone: async (...args) => calls.push(['delete', ...args]),
    putVideoJobConfig: async (...args) => calls.push(['video', ...args]),
  };
  const writes = createGateZoneWrites(api);
  await writes.create('a1', zone);
  await writes.update('a1', 'z1', { name: 'Changed' });
  await writes.setEnabled('a1', 'z1', true);
  await writes.remove('a1', 'z1');
  await writes.saveVideo('j1', { zones: [zone] });
  assert.deepEqual(calls.map((item) => item[0]), ['create', 'update', 'update', 'delete', 'video']);
  assert.deepEqual(calls[2].slice(1), ['a1', 'z1', { enabled: true }]);
});
