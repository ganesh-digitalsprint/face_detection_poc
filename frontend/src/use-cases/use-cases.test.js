import assert from 'node:assert/strict';
import { test } from 'node:test';

// Mocked/unit-level: no backend is contacted. Verifies each use case exposes its own API module.
const vault = await import('./vault-monitoring/api/vaultRoom.js');
const alerts = await import('./vault-monitoring/api/alerts.js');
const branch = await import('./branch-exterior/api/index.js');

test('vault-monitoring API modules export request functions', () => {
  for (const fn of ['getVaultRoomState', 'closeVault', 'getVaultSessions', 'analyzeVaultFrame', 'openVaultEvents']) {
    assert.equal(typeof vault[fn], 'function', fn);
  }
  for (const fn of ['getAlerts', 'getIncident', 'updateAlert', 'getEvidenceAccess']) {
    assert.equal(typeof alerts[fn], 'function', fn);
  }
});

test('normalizeAlert maps backend fields and defaults allowed actions', () => {
  const a = alerts.normalizeAlert({ id: 'x', alert_type: 't', session_ref: 's' });
  assert.equal(a.type, 't');
  assert.equal(a.sessionRef, 's');
  assert.deepEqual(a.allowedActions, []);
});

test('branch-exterior API resolves against the Branch base, not Vault', () => {
  assert.equal(branch.BX_BASE, 'http://localhost:8011');
  assert.ok(branch.bxApiUrl('/x').startsWith('http://localhost:8011'));
});
