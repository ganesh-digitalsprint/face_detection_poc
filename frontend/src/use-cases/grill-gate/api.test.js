import assert from 'node:assert/strict';
import { test } from 'node:test';
import client from '../../api/client.js';
import { getLiveActiveAlerts, startGrillGateVideoJob, uploadGrillGateVideo } from './api/grillGate.js';
import { gateUploadBranchId, gateUploadBranchValidationMessage } from './videoJobModel.js';

test('Grill Gate uses only the specific shared active branch; All branches requires a new selection', () => {
  assert.equal(gateUploadBranchId({ type: 'branch', id: 'old-goa', name: 'Old Goa' }), 'old-goa');
  assert.equal(gateUploadBranchId({ type: 'branch', id: 'koramangala', name: 'Koramangala' }), 'koramangala');
  assert.equal(gateUploadBranchId(null), null);
  assert.equal(gateUploadBranchId({ type: 'city', id: 'bengaluru' }), null);
  assert.equal(gateUploadBranchId({ type: 'zone', id: 'south' }), null);
  assert.match(gateUploadBranchValidationMessage(null), /All branches is selected/);
  assert.match(gateUploadBranchValidationMessage({ type: 'city', id: 'bengaluru' }), /specific branch/);
  assert.equal(gateUploadBranchValidationMessage({ type: 'branch', id: 'old-goa' }), '');
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

test('uploaded Gate video sends selected branch and camera metadata', async () => {
  const originalAdapter = client.defaults.adapter;
  let request;
  client.defaults.adapter = async (config) => {
    request = config;
    return { data: { job_id: 'job-1', status: 'UPLOADED' }, status: 201,
      statusText: 'Created', headers: {}, config };
  };
  try {
    const file = new File(['video'], 'gate.mp4', { type: 'video/mp4' });
    for (const scope of [
      { type: 'branch', id: 'old-goa', name: 'Old Goa' },
      { type: 'branch', id: 'koramangala', name: 'Koramangala' },
    ]) {
      const branchId = gateUploadBranchId(scope);
      await uploadGrillGateVideo(file, null, { branchId, cameraId: 'camera-1', cameraLabel: 'Front gate' });
      assert.equal(request.url, '/api/v1/grill-gate/videos');
      assert.equal(request.data.get('branch_id'), branchId);
      assert.equal(request.data.get('camera_id'), 'camera-1');
      assert.equal(request.data.get('camera_label'), 'Front gate');
      assert.equal(request.data.get('template_assignment_id'), null);
    }
  } finally {
    client.defaults.adapter = originalAdapter;
  }
});

test('starting Gate processing does not replace immutable upload attribution', async () => {
  const originalAdapter = client.defaults.adapter;
  let request;
  client.defaults.adapter = async (config) => {
    request = config;
    return { data: { job_id: 'job-1', status: 'QUEUED' }, status: 202,
      statusText: 'Accepted', headers: {}, config };
  };
  try {
    await startGrillGateVideoJob('job-1');
    assert.equal(request.url, '/api/v1/grill-gate/videos/job-1/start');
    assert.equal(request.data, undefined);
  } finally {
    client.defaults.adapter = originalAdapter;
  }
});
