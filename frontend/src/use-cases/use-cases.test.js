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

test('normalizeAlert maps uploaded-video detection metadata and defaults allowed actions', () => {
  const a = alerts.normalizeAlert({ id: 'x', alert_type: 'MOBILE_PHONE_DETECTED', session_ref: 's',
    source_type:'uploaded_video',camera_name:'Uploaded video',video_timestamp_seconds:18.75,
    mobile_phone_confidence:.781,mobile_phone_confirmation_seconds:1,
    mobile_phone_detections:[{bbox:[.1,.2,.3,.4]}],branch_name:'Koramangala' });
  assert.equal(a.type, 'MOBILE_PHONE_DETECTED');
  assert.equal(a.sessionRef, 's');
  assert.deepEqual(a.allowedActions, []);
  assert.equal(a.sourceType,'uploaded_video'); assert.equal(a.cameraName,'Uploaded video');
  assert.equal(a.videoTimestampSeconds,18.75); assert.equal(a.mobilePhoneConfidence,.781);
  assert.deepEqual(a.mobilePhoneDetections,[{bbox:[.1,.2,.3,.4]}]); assert.equal(a.branchName,'Koramangala');
});

test('branch-exterior API resolves against the Branch base, not Vault', () => {
  assert.equal(branch.BX_BASE, 'http://localhost:8011');
  assert.ok(branch.bxApiUrl('/x').startsWith('http://localhost:8011'));
});
