import assert from 'node:assert/strict';
import test from 'node:test';

import client from '../../../api/client.js';
import { startLivenessSession } from './vault.js';
import { analyzeVaultFrame, startRoomBrowserSource, startRoomRtspCamera } from './vaultRoom.js';

const jsonBody = (data) => typeof data === 'string' ? JSON.parse(data) : data;

test('Vault session and camera creation send the captured canonical branch ID', async () => {
  const originalAdapter = client.defaults.adapter;
  const requests = [];
  client.defaults.adapter = async (config) => {
    requests.push(config);
    return { data: config.url.includes('vault-authentication')
      ? { session_ref: 'access-1' } : { session_id: 'source-1', stream_url: '/stream' },
    status: 200, statusText: 'OK', headers: {}, config };
  };
  try {
    await startLivenessSession(2, { branchId: 'branch-1', cameraLabel: 'Entrance Camera' });
    await startRoomBrowserSource('Vault Room Camera', 'branch-1');
    await startRoomRtspCamera('Rear RTSP', 'rtsp://camera.local/live', false, 'branch-1');

    assert.deepEqual(jsonBody(requests[0].data), {
      required_persons: 2, branch_id: 'branch-1', camera_label: 'Entrance Camera',
    });
    assert.equal(jsonBody(requests[1].data).branch_id, 'branch-1');
    assert.equal(jsonBody(requests[1].data).name, 'Vault Room Camera');
    assert.equal(jsonBody(requests[2].data).branch_id, 'branch-1');
    assert.equal(jsonBody(requests[2].data).name, 'Rear RTSP');
  } finally {
    client.defaults.adapter = originalAdapter;
  }
});

test('browser frames send only the immutable source-session identity', async () => {
  const originalAdapter = client.defaults.adapter;
  let request;
  client.defaults.adapter = async (config) => {
    request = config;
    return { data: { accepts_frames: true }, status: 200, statusText: 'OK', headers: {}, config };
  };
  try {
    await analyzeVaultFrame(new Blob(['frame'], { type: 'image/jpeg' }), undefined, false, 'source-1');
    assert.equal(request.data.get('source_session_id'), 'source-1');
    assert.equal(request.data.get('branch_id'), null);
  } finally {
    client.defaults.adapter = originalAdapter;
  }
});
