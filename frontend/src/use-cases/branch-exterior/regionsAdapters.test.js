import test from 'node:test';
import assert from 'node:assert/strict';
import { branchCamerasForLocation, buildBranchAdapter, buildRegistryAdapter, buildZoneSavePayload, REGIONS_ADAPTERS, selectionResponseIsCurrent } from './regionsAdapters.js';
import { cloneZoneSnapshot, isRegionsDraftDirty } from './regionsPageState.js';

test('Branch adapter keeps camera and zone requests on the current Branch API contract', async () => {
  const calls = [];
  const client = {
    get: async (path) => { calls.push(['get', path]); return path === '/cameras' ? [] : {}; },
    post: async (path, body) => { calls.push(['post', path, body]); return { id: 'zone-1' }; },
    patch: async (path, body) => { calls.push(['patch', path, body]); return {}; },
    del: async (path) => { calls.push(['del', path]); return {}; },
  };
  const adapter = buildBranchAdapter(client);
  await adapter.listCameras();
  await adapter.listCameraStatuses();
  await adapter.loadZones('cam / 1');
  assert.deepEqual(calls, [
    ['get', '/cameras'],
    ['get', '/cameras/status/all'],
    ['get', '/zones?camera_id=cam%20%2F%201'],
  ]);
});

test('new zone save payload keeps camera_id and existing normalized zone fields', () => {
  const polygon = [{ x: 0.1, y: 0.2 }, { x: 0.8, y: 0.2 }, { x: 0.5, y: 0.9 }];
  const body = { name: 'Entrance', zone_type: 'entrance', restricted: false, alert_mode: 'suspicious', alert_severity: 'high' };
  assert.deepEqual(buildZoneSavePayload('camera-7', body, polygon), { camera_id: 'camera-7', ...body, polygon });
  assert.deepEqual(buildZoneSavePayload('camera-7', body, polygon, true), { ...body, polygon });
});

test('Branch camera filtering takes the camera list before the selected location', () => {
  const cameras = [
    { id: 'cam-a', location: 'Branch A' },
    { id: 'cam-b', location: 'Branch B' },
    { id: 'cam-c', location: '' },
  ];
  assert.deepEqual(branchCamerasForLocation(cameras, 'Branch A'), [cameras[0]]);
  assert.deepEqual(branchCamerasForLocation(cameras, '__unassigned__'), [cameras[2]]);
});

test('common adapter scopes cameras and zones to use-case assignments and maps normalized polygons', async () => {
  const calls = [];
  const client = {
    get: async (path) => { calls.push(['get', path]); return path.endsWith('/zones') ? [{ id: 'door', polygon: [[0.1, 0.2], [0.8, 0.2], [0.5, 0.9]] }] : []; },
    post: async (path, body) => calls.push(['post', path, body]),
    patch: async (path, body) => calls.push(['patch', path, body]),
    del: async (path) => calls.push(['del', path]),
  };
  const adapter = buildRegistryAdapter(client, 'vault-room');
  await adapter.listCameras('location-1');
  const zones = await adapter.loadZones('assignment-1');
  await adapter.saveZone('assignment-1', null, { name: 'Vault Area', reference: 'center' }, zones[0].polygon);
  assert.deepEqual(zones[0].polygon, [{ x: 0.1, y: 0.2 }, { x: 0.8, y: 0.2 }, { x: 0.5, y: 0.9 }]);
  assert.equal(calls[0][1], '/cameras?use_case=vault_room&location_id=location-1');
  assert.equal(calls[1][1], '/assignments/assignment-1/zones');
  assert.equal(calls[2][2].coordinate_system, undefined);
  assert.equal(calls[2][2].zone_key, 'vault-area');
});

test('common registry adapters expose their service boundary while the legacy editor remains Branch-only', () => {
  const [branch, vault, grill] = REGIONS_ADAPTERS;
  assert.equal(branch.enabled, true);
  assert.equal(vault.enabled, false);
  assert.equal(grill.enabled, false);
  assert.equal('listCameras' in vault, true);
  assert.equal('loadZones' in grill, true);
});

test('draft tracking identifies new drawings, edits, and changed zone form values', () => {
  const points = [{ x: 1, y: 1 }, { x: 8, y: 1 }, { x: 4, y: 8 }];
  assert.equal(isRegionsDraftDirty({}), false);
  assert.equal(isRegionsDraftDirty({ drawing: true, drawPoints: points }), true);
  assert.equal(isRegionsDraftDirty({ drawing: true, editingZoneId: 'z1', drawPoints: points, editOriginal: points }), false);
  assert.equal(isRegionsDraftDirty({ drawing: true, editingZoneId: 'z1', drawPoints: points.slice(1), editOriginal: points }), true);
  assert.equal(isRegionsDraftDirty({ zoneFormDirty: true }), true);
  assert.deepEqual(cloneZoneSnapshot([{ id: 'z1', polygon: points }]), [{ id: 'z1', polygon: points }]);
});

test('stale camera responses are accepted only for the latest selected camera', () => {
  assert.equal(selectionResponseIsCurrent(3, 3, 'cam-a', 'cam-a'), true);
  assert.equal(selectionResponseIsCurrent(2, 3, 'cam-a', 'cam-a'), false);
  assert.equal(selectionResponseIsCurrent(3, 3, 'cam-a', 'cam-b'), false);
});
