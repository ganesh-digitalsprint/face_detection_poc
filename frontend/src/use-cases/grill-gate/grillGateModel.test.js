import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  CALIBRATION_STARTING_VALUES, calibrationFormIsBlank, calibrationFromForm, calibrationStatus, calibrationToForm, connectionView, EMPTY_MONITORING, formatClock, formLine, formToCalibration, mergeAssignmentConfiguration, mergeGrillGateAlertConfiguration,
  gateStateView, previewState, workerForAssignment, workerIsActive, workerPollDelay, zoneCoverage,
  zoneTypesForStrategy,
} from './grillGateModel.js';

// Shapes copied from GrillGateCameraWorker.status() and GrillGateCalibration (backend Stage 1).
const worker = (status, extra = {}) => ({
  camera_id: 'cam-1', assignment_id: 'asg-1', source_type: 'rtsp', status, error: null, sequence_number: 4,
  width: 1280, height: 720, last_frame_at: null, frame_age_seconds: 0.2, reconnect_attempt: 0, consumer_count: 0, ...extra,
});
const calibration = {
  schema_version: 1, reference_frame: { width: 1280, height: 720 }, coordinate_system: 'normalized_raw',
  calibrated_at: '2026-11-04T05:00:00+00:00',
  sliding_gate: { gate_roi_zone_key: 'gate_leaf_roi', closed_reference_position: 0.2, open_reference_position: 0.8,
    horizontal_movement_direction: 'left_to_right', position_thresholds: { closed_tolerance: 0.05, open_tolerance: 0.05 },
    confidence_threshold: 0.6, hysteresis_fraction: 0.1,
    partially_open_threshold_percent: 25, partially_open_exit_threshold_percent: 20,
    fully_open_threshold_percent: 80, fully_open_hysteresis_percent: 5,
    state_confirmation_durations: { closed_seconds: 1, opening_seconds: 1, open_seconds: 1, partially_open_seconds: 1, closing_seconds: 1 } },
  directional_crossing: { line_start: { x: 0.1, y: 0.5 }, line_end: { x: 0.9, y: 0.5 }, outside_side: 'left', inside_side: 'right',
    entry_direction: 'outside_to_inside', exit_direction: 'inside_to_outside', dead_band_fraction: 0.02, minimum_crossing_displacement: 0.05 },
  monitoring: { thresholds_status: 'unset', maximum_continuous_open_seconds: null, crossing_inactivity_seconds: null,
    minimum_mesh_gathering_count: null, mesh_gathering_seconds: null, suspicious_activity_seconds: null },
};

test('only the supported Three-Zone types are offered', () => {
  const types = ['gate_leaf_roi', 'gate_approach', 'gate_interior', 'mesh_area']
    .map((key) => ({ key }));
  assert.deepEqual(zoneTypesForStrategy(types).map(({ key }) => key),
    ['gate_leaf_roi', 'gate_approach', 'gate_interior', 'mesh_area']);
});

test('legacy transitional and OPEN states map to the three gate cards', () => {
  assert.equal(gateStateView('OPEN'), 'FULLY_OPEN');
  assert.equal(gateStateView('OPENING'), 'PARTIALLY_OPEN');
  assert.equal(gateStateView('CLOSING'), 'PARTIALLY_OPEN');
  assert.equal(gateStateView('UNKNOWN'), 'UNKNOWN');
});

test('changing the assignment source keeps its alert rules', () => {
  const rules = { gate_open_enabled: true, max_gate_open_seconds: 120 };
  assert.deepEqual(mergeAssignmentConfiguration({ source_id: 'old', grill_gate_alerts: rules }, { source_id: 'new' }),
    { source_id: 'new', grill_gate_alerts: rules });
  assert.deepEqual(mergeAssignmentConfiguration(null, { source_id: 'new' }), { source_id: 'new' });
});

test('saving alert thresholds preserves the assignment config and other alert rules', () => {
  const current = { source_id: 'source-1', other_setting: 'keep', grill_gate_alerts: {
    gate_open_enabled: true, max_gate_open_seconds: 30, mesh_occupancy_enabled: true, max_mesh_occupancy: 8,
  } };
  for (const seconds of [3, 4, 10, 30]) {
    assert.deepEqual(mergeGrillGateAlertConfiguration(current, {
      ...current.grill_gate_alerts, max_gate_open_seconds: seconds,
    }), { ...current, grill_gate_alerts: { ...current.grill_gate_alerts, max_gate_open_seconds: seconds } });
  }
});

test('calibration form: blank stays unsaved, starting values are explicit, reference positions stay fixed', () => {
  const blank = calibrationToForm(null, { width: 640, height: 360 });
  assert.ok(calibrationFormIsBlank(blank));
  assert.equal(calibrationFromForm(blank, { width: 640, height: 360 }), null);
  const document = calibrationFromForm({ ...blank, ...CALIBRATION_STARTING_VALUES }, { width: 640, height: 360 });
  assert.deepEqual(document.reference_frame, { width: 640, height: 360 });
  assert.equal(document.sliding_gate.position_thresholds.closed_tolerance, 0.1);
  assert.deepEqual(document.sliding_gate.state_confirmation_durations, { closed_seconds: 0.5, opening_seconds: 0.3, open_seconds: 0.5, partially_open_seconds: 1, closing_seconds: 0.3 });
  assert.deepEqual([document.sliding_gate.closed_reference_position, document.sliding_gate.open_reference_position], [0, 1]);
});

test('workers are matched by assignment, not just camera', () => {
  assert.equal(workerForAssignment([worker('connected')], 'asg-1').status, 'connected');
  assert.equal(workerForAssignment([worker('connected', { assignment_id: 'other' })], 'asg-1'), null);
});

test('connection view distinguishes available, starting, connected, stale, disconnected and failed', () => {
  assert.equal(connectionView(null).key, 'available');
  assert.equal(connectionView(worker('connecting')).key, 'starting');
  assert.equal(connectionView(worker('connected')).key, 'connected');
  assert.equal(connectionView(worker('stale', { error: 'No fresh camera frame' })).detail, 'No fresh camera frame');
  assert.equal(connectionView(worker('stopped')).key, 'disconnected');
  assert.equal(connectionView(worker('failed')).key, 'failed');
  assert.match(connectionView(worker('reconnecting', { reconnect_attempt: 3 })).detail, /Attempt 3/);
});

test('a failed status check never reports the last-known connected state', () => {
  assert.equal(connectionView(worker('connected'), { statusError: 'Cannot reach the API.' }).key, 'unknown');
});

test('polling is bounded and slows down once settled', () => {
  assert.equal(workerPollDelay(worker('connecting')), 2000);
  assert.equal(workerPollDelay(worker('connected')), 5000);
  assert.equal(workerPollDelay(worker('failed')), 15000);
  assert.equal(workerPollDelay(null), 15000);
  assert.ok(workerIsActive(worker('stale')) && !workerIsActive(worker('stopped')));
});

test('calibration status reports missing, mismatch and missing gate zone', () => {
  assert.equal(calibrationStatus(null).key, 'missing');
  const status = calibrationStatus(calibration, { worker: worker('connected', { width: 1920, height: 1080 }), zones: [] });
  assert.equal(status.key, 'attention');
  assert.ok(status.issues.some((issue) => issue.includes('1920×1080')));
  assert.ok(status.issues.some((issue) => issue.includes('gate_leaf_roi')));
  assert.equal(calibrationStatus({ schema_version: 2 }).key, 'invalid');
});

test('calibration round-trips and supplies defaults for hidden advanced fields', () => {
  const doc = formToCalibration(calibrationToForm(calibration), new Date('2026-11-04T05:00:00Z'));
  assert.deepEqual(doc.directional_crossing, calibration.directional_crossing);
  assert.deepEqual(doc.sliding_gate, calibration.sliding_gate);
  assert.deepEqual(doc.monitoring, calibration.monitoring);
  const blank = formToCalibration(calibrationToForm(null));
  assert.equal(blank.monitoring.maximum_continuous_open_seconds, null);
  assert.equal(blank.sliding_gate.confidence_threshold, 0.5);
  assert.equal(blank.sliding_gate.horizontal_movement_direction, null);
  assert.equal(blank.directional_crossing, undefined, 'an ENTRY/EXIT line is optional for Three-Zone video processing');
  const withLine = calibrationFromForm({ ...calibrationToForm(null), line_start_x: '0.1', line_start_y: '0.5',
    line_end_x: '0.9', line_end_y: '0.5' }, { width: 640, height: 360 });
  assert.equal(withLine.sliding_gate.position_thresholds.closed_tolerance, 0.1);
  assert.equal(withLine.directional_crossing.dead_band_fraction, 0.05);
});

test('legacy partial-open defaults migrate to the 25/20 percent hysteresis band', () => {
  const legacy = { ...calibration, sliding_gate: { ...calibration.sliding_gate,
    partially_open_threshold_percent: 30, partially_open_exit_threshold_percent: 25 } };
  const form = calibrationToForm(legacy);
  assert.equal(form.partially_open_threshold_percent, '25');
  assert.equal(form.partially_open_exit_threshold_percent, '20');
});

test('line preview requires both endpoints within the normalized range', () => {
  assert.equal(formLine(calibrationToForm(null)), null);
  assert.deepEqual(formLine(calibrationToForm(calibration)), { start: { x: 0.1, y: 0.5 }, end: { x: 0.9, y: 0.5 } });
});

test('zone coverage lists every type and keeps unknown types visible', () => {
  const rows = zoneCoverage([{ key: 'mesh_area', label: 'Mesh' }], [{ id: 'a', zone_type: 'mesh_area' }, { id: 'b', zone_type: 'legacy' }]);
  assert.equal(rows[0].zones.length, 1);
  assert.equal(rows.at(-1).key, '__other');
});

test('dashboard empty state uses neutral defaults and no fabricated records', () => {
  assert.equal(EMPTY_MONITORING.status, 'INACTIVE');
  assert.equal(EMPTY_MONITORING.gateState, 'UNKNOWN');
  for (const key of ['gateOpenSeconds', 'secondsSinceCrossing', 'entryCount', 'exitCount', 'meshPeopleCount', 'meshGatheringSeconds']) {
    assert.equal(EMPTY_MONITORING[key], 0, key);
  }
  for (const key of ['crossings', 'alerts', 'events']) assert.deepEqual(EMPTY_MONITORING[key], [], key);
});

test('timers format as mm:ss and default to 00:00', () => {
  assert.equal(formatClock(0), '00:00');
  assert.equal(formatClock(null), '00:00');
  assert.equal(formatClock(342), '05:42');
  assert.equal(formatClock(3725), '1:02:05');
});

test('camera preview offers Connect only when no worker is running', () => {
  assert.equal(previewState(connectionView(null)).title, 'No Camera Connected');
  assert.ok(previewState(connectionView(null)).canConnect);
  assert.ok(previewState(connectionView(worker('failed'))).canConnect);
  assert.equal(previewState(connectionView(worker('connected'))).canConnect, false);
  assert.equal(previewState(connectionView(worker('connecting'))).key, 'busy');
  assert.equal(previewState(connectionView(null, { statusError: 'down' })).key, 'unknown');
});
