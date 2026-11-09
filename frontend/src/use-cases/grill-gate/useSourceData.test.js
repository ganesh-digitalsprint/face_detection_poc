import assert from 'node:assert/strict';
import { test } from 'node:test';
import client from '../../api/client.js';
import { fetchLiveMonitoringData } from './hooks/useSourceData.js';

test('a live assignment poll sends the local active-alert request even when no gate worker is running', async () => {
  const originalAdapter = client.defaults.adapter;
  const requests = [];
  client.defaults.adapter = async (config) => {
    requests.push(config);
    let data = { items: [], count: 0, total: 0, limit: 25, offset: 0 };
    if (config.url.endsWith('/mesh-status')) data = { occupancy_count: 0 };
    return { data, status: 200, statusText: 'OK', headers: {}, config };
  };
  try {
    const result = await fetchLiveMonitoringData('assignment-123', false, new AbortController().signal);
    const alertRequest = requests.find((request) => request.url.endsWith('/alerts/active'));
    assert.ok(alertRequest, 'local active-alert route should be requested');
    assert.equal(alertRequest.url, '/api/v1/grill-gate/assignments/assignment-123/alerts/active');
    assert.equal(result[6].status, 'fulfilled');
    assert.deepEqual(result[6].value.items, []);
  } finally {
    client.defaults.adapter = originalAdapter;
  }
});

test('live monitoring does not request scoped alerts before an assignment is selected', async () => {
  assert.equal(await fetchLiveMonitoringData('', false, new AbortController().signal), null);
});
