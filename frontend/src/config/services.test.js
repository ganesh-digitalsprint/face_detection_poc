import assert from 'node:assert/strict';
import { test } from 'node:test';

// Under `node --test` there is no import.meta.env, so these assert the built-in local development defaults.
const config = await import('./services.js');
const branch = await import('../use-cases/branch-exterior/api/index.js');
const streams = await import('../api/streams.js');

test('service URLs default to the documented local ports', () => {
  assert.equal(config.VAULT_BASE_URL, 'http://localhost:8010');
  assert.equal(config.BRANCH_BASE_URL, 'http://localhost:8011');
  assert.equal(config.ALERT_SERVICE_BASE_URL, '/alert-service');
});

test('Alert Service lifecycle actions are off by default and polling has a floor', () => {
  assert.equal(config.ALERT_SERVICE_ACTIONS_ENABLED, false);
  assert.ok(config.ALERT_POLL_MS >= 3000);
});

test('the Alert Service base is same-origin so no credential is needed in the browser', () => {
  assert.ok(config.ALERT_SERVICE_BASE_URL.startsWith('/'));
});

test('Branch URL helpers are built from the single configured base', () => {
  assert.equal(branch.BX_BASE, 'http://localhost:8011');
  assert.equal(branch.bxApiUrl('/streams/c1/processed'), 'http://localhost:8011/api/streams/c1/processed');
  assert.equal(branch.bxStorageUrl('snapshots/a.jpg'), 'http://localhost:8011/storage/snapshots/a.jpg');
  assert.equal(branch.bxWsUrl(), 'ws://localhost:8011/api/ws/alerts');
});

test('Vault stream URLs resolve against the Vault base, absolute URLs pass through', () => {
  assert.equal(streams.resolveStreamUrl({ session_id: 's1' }), 'http://localhost:8010/api/v1/streams/s1/stream');
  assert.equal(streams.resolveStreamUrl({ session_id: 's1', stream_url: '/api/v1/streams/s1/stream' }), 'http://localhost:8010/api/v1/streams/s1/stream');
  assert.equal(streams.resolveStreamUrl({ session_id: 's1', stream_url: 'https://cams.example/s1' }), 'https://cams.example/s1');
});
