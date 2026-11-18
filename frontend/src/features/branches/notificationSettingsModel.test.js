import test from 'node:test';
import assert from 'node:assert/strict';
import { createSubmissionGate, defaultNotificationSettings, isEmail, notificationSettingsChanged, settingsFromApi, settingsToApi, toggleNotificationRule } from './notificationSettingsModel.js';

test('notification defaults are scoped to the selected branch', () => {
  const first = defaultNotificationSettings({ id: 'b1', name: 'Chennai B1', email: 'chennai@example.invalid' });
  const second = defaultNotificationSettings({ id: 'b2', name: 'South City', email: 'south@example.invalid' });
  assert.equal(first.branchId, 'b1');
  assert.equal(first.email.enabled, false);
  assert.deepEqual(first.email.recipients, []);
  assert.equal(second.branchId, 'b2');
  assert.notEqual(first.branchId, second.branchId);
});

test('API settings round-trip preserves recipients, filters and evidence preferences', () => {
  const value = { email_enabled: true, to_recipients: ['a@example.invalid', 'b@example.invalid'],
    severity_filters: ['critical', 'info'], use_case_filters: ['grill_gate', 'branch_exterior'],
    include_snapshot: true, include_video_evidence: false, delivery_mode: 'instant' };
  const loaded = settingsFromApi({ id: 'b1' }, value);
  assert.deepEqual(settingsToApi(loaded), value);
});

test('submission gate prevents duplicate test email requests', async () => {
  const gate = createSubmissionGate();
  let release;
  let calls = 0;
  const pending = gate.run(() => { calls += 1; return new Promise((resolve) => { release = resolve; }); });
  const duplicate = await gate.run(() => { calls += 1; });
  assert.deepEqual(duplicate, { skipped: true });
  assert.equal(calls, 1);
  release({ status: 'accepted' });
  await pending;
});

test('send rules toggle immutably and participate in dirty state', () => {
  const saved = defaultNotificationSettings({ id: 'b1', name: 'Chennai B1' });
  const changed = toggleNotificationRule(saved, 'severity', 'warning');
  assert.equal(saved.severity.warning, false);
  assert.equal(changed.severity.warning, true);
  assert.equal(notificationSettingsChanged(changed, saved), true);
});

test('recipient validation accepts email addresses and rejects incomplete values', () => {
  assert.equal(isEmail('ops.chennai@fedbank.example'), true);
  assert.equal(isEmail('ops.chennai'), false);
});
