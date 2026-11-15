import assert from 'node:assert/strict';
import { test } from 'node:test';
import client from '../../api/client.js';
import { getLiveActiveAlerts, uploadGrillGateVideo } from './api/grillGate.js';
import { gateUploadBranchId } from './videoJobModel.js';

test('Gate uploads reuse only the canonical globally selected branch scope', () => {
  assert.equal(gateUploadBranchId({ type: 'branch', id: 'branch-1', name: 'Koramangala' }), 'branch-1');
  assert.equal(gateUploadBranchId({ type: 'city', id: 'city-1' }), null);
  assert.equal(gateUploadBranchId({ type: 'zone', id: 'zone-1' }), null);
  assert.equal(gateUploadBranchId(null), null);
});

test('live alert polling sends an authenticated-client request to the local assignment-scoped API', async () => {
  const originalAdapter = client.defaults.adapter;
  let request;
  client.defaults.adapter = async (config) => {
    request = config;
    return { data: { items: [], count: 0, total: 0, limit: 25, offset: 0 }, status: 200,
      statusText: 'OK', headers: {}, config };
  };
  try {
    const response = await getLiveActiveAlerts('assignment-123', { limit: 25 });
    assert.deepEqual(response, { items: [], count: 0, total: 0, limit: 25, offset: 0 });
    assert.equal(request.url, '/api/v1/grill-gate/assignments/assignment-123/alerts/active');
    assert.equal(request.params.limit, 25);
  } finally {
    client.defaults.adapter = originalAdapter;
  }
});

test('uploaded Gate video sends optional branch metadata without a camera assignment', async () => {
  const originalAdapter = client.defaults.adapter;
  let request;
  client.defaults.adapter = async (config) => {
    request = config;
    return { data: { job_id: 'job-1', status: 'UPLOADED' }, status: 201,
      statusText: 'Created', headers: {}, config };
  };
  try {
    const file = new File(['video'], 'gate.mp4', { type: 'video/mp4' });
    await uploadGrillGateVideo(file, null, { branchId: 'branch-1', cameraLabel: 'Upload desk camera' });
    assert.equal(request.url, '/api/v1/grill-gate/videos');
    assert.equal(request.data.get('branch_id'), 'branch-1');
    assert.equal(request.data.get('camera_label'), 'Upload desk camera');
    assert.equal(request.data.get('template_assignment_id'), null);
  } finally {
    client.defaults.adapter = originalAdapter;
  }
});
