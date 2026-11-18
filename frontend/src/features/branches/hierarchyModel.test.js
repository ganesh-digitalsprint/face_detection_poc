import test from 'node:test';
import assert from 'node:assert/strict';
import { cameraState, createLatestLoader, hierarchySearch } from './hierarchyModel.js';

test('hierarchy navigation clears descendants and preserves valid ancestors', () => {
  assert.equal(hierarchySearch('zone', 'z2', { zoneId: 'z1', cityId: 'c1' }).toString(), 'zone=z2');
  assert.equal(hierarchySearch('city', 'c2', { zoneId: 'z1', cityId: 'c1' }).toString(), 'zone=z1&city=c2');
  assert.equal(hierarchySearch('branch', 'b2', { zoneId: 'z1', cityId: 'c1' }).toString(), 'zone=z1&city=c1&branch=b2');
});

test('only the latest selected branch can publish its cameras', async () => {
  const pending = new Map();
  const api = (branch) => new Promise((resolve) => pending.set(branch, resolve));
  const loader = createLatestLoader();
  let shown = [];
  const oldRequest = loader.run(() => api('old'), { success: (rows) => { shown = rows; } });
  const newRequest = loader.run(() => api('new'), { success: (rows) => { shown = rows; } });
  pending.get('new')([{ id: 'new-camera' }]);
  await newRequest;
  pending.get('old')([{ id: 'stale-camera' }]);
  await oldRequest;
  assert.deepEqual(shown, [{ id: 'new-camera' }]);
});

test('camera state distinguishes loading, empty, and populated branches', () => {
  assert.equal(cameraState({ loading: true, cameras: [] }), 'loading');
  assert.equal(cameraState({ loading: false, cameras: [] }), 'empty');
  assert.equal(cameraState({ loading: false, cameras: [{ id: 'c1' }] }), 'ready');
});
