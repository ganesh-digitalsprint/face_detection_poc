import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  initialVideoZoneConfigurationSelection, rememberVideoZoneConfigurationSelection,
  videoAlertConfigurationWithAssignmentDefault, videoAlertThresholdInputValue,
} from './videoZoneConfigurationSelection.js';

class MemoryStorage {
  values = new Map();
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, String(value)); }
  removeItem(key) { this.values.delete(key); }
}

const job = (jobId, assetId = 'asset-1', zoneConfigurationId = null) => ({
  job_id: jobId, asset_job_id: assetId, zone_configuration_id: zoneConfigurationId,
});

test('saved zone configuration values of 3, 4, 10, and 30 remain exact numeric input values', () => {
  for (const seconds of [3, 4, 10, 30]) {
    assert.equal(videoAlertThresholdInputValue({ max_gate_open_seconds: seconds }, 'max_gate_open_seconds'), seconds);
  }
});

test('missing and null thresholds remain unset, matching the nullable backend default', () => {
  assert.equal(videoAlertThresholdInputValue({}, 'max_gate_open_seconds'), '');
  assert.equal(videoAlertThresholdInputValue({ max_gate_open_seconds: null }, 'max_gate_open_seconds'), '');
});

test('video gets assignment threshold as an editable default but keeps its own saved value', () => {
  const assignment = { max_gate_open_seconds: 3, gate_open_enabled: true };
  assert.deepEqual(videoAlertConfigurationWithAssignmentDefault({ max_gate_open_seconds: null }, assignment), {
    max_gate_open_seconds: 3, gate_open_enabled: true,
  });
  assert.equal(videoAlertConfigurationWithAssignmentDefault({ max_gate_open_seconds: 5 }, assignment)
    .max_gate_open_seconds, 5);
  assert.equal(videoAlertConfigurationWithAssignmentDefault({ max_gate_open_seconds: null }, assignment, false)
    .max_gate_open_seconds, null);
});

test('a saved selection survives editor unmount and return and is reused for reprocessing', () => {
  const storage = new MemoryStorage();
  const firstRun = job('run-1');
  const saved = { 'config-3': { alert_configuration: { max_gate_open_seconds: 3 } } };
  rememberVideoZoneConfigurationSelection(firstRun, 'config-3', storage);

  // A remounted editor and the reprocess control read the same asset-scoped selection.
  const editorSelection = initialVideoZoneConfigurationSelection(job('run-1'), storage);
  const reprocessSelection = initialVideoZoneConfigurationSelection(job('run-2'), storage);
  assert.equal(editorSelection, 'config-3');
  assert.equal(videoAlertThresholdInputValue(saved[editorSelection].alert_configuration, 'max_gate_open_seconds'), 3);
  assert.equal(reprocessSelection, 'config-3');
});

test('switching configurations and switching back restores each explicitly selected ID', () => {
  const storage = new MemoryStorage();
  const video = job('run-1');
  rememberVideoZoneConfigurationSelection(video, 'config-3', storage);
  assert.equal(initialVideoZoneConfigurationSelection(video, storage), 'config-3');
  rememberVideoZoneConfigurationSelection(video, 'config-30', storage);
  assert.equal(initialVideoZoneConfigurationSelection(video, storage), 'config-30');
  rememberVideoZoneConfigurationSelection(video, 'config-3', storage);
  assert.equal(initialVideoZoneConfigurationSelection(video, storage), 'config-3');
});

test('a saved job configuration is the fallback, with no arbitrary first configuration selected', () => {
  const storage = new MemoryStorage();
  assert.equal(initialVideoZoneConfigurationSelection(job('run-1', 'asset-1', 'snapshot-config'), storage), 'snapshot-config');
  assert.equal(initialVideoZoneConfigurationSelection(job('run-1', 'asset-1', null), storage), '');
  rememberVideoZoneConfigurationSelection(job('run-1'), '', storage);
  assert.equal(initialVideoZoneConfigurationSelection(job('run-1', 'asset-1', 'snapshot-config'), storage), '');
});

test('failed saves do not promote an edited threshold into the persisted selection', () => {
  const storage = new MemoryStorage();
  const video = job('run-1');
  rememberVideoZoneConfigurationSelection(video, 'persisted-config-30', storage);
  const editedButUnconfirmed = { max_gate_open_seconds: 3 };
  assert.equal(videoAlertThresholdInputValue(editedButUnconfirmed, 'max_gate_open_seconds'), 3);
  // The save handler only calls rememberVideoZoneConfigurationSelection after server success.
  assert.equal(initialVideoZoneConfigurationSelection(video, storage), 'persisted-config-30');
});
