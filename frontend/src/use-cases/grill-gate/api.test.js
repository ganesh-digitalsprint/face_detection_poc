import assert from 'node:assert/strict';
import { test } from 'node:test';
import client from '../../api/client.js';
import { getLiveActiveAlerts } from './api/grillGate.js';

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
