import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createVideoJobPoller } from './videoJobPoller.js';
import {
  formatVideoTime, jobCanCancel, jobPillLabel, jobCanStart, jobIsActive, jobProgressPercent, mergeEvents, processingFps,
  templateBlocker, validateVideoFile, videoMonitoring, localVideoConfiguration, videoUploadConfiguration,
} from './videoJobModel.js';

// Shapes copied from _job_dict and GET /videos/{job_id}/results in grill_gate_monitoring/api/grill_gate.py.
const job = (status, extra = {}) => ({
  job_id: 'job-1', filename: 'gate.mp4', status, template_assignment_id: 'asg-1', frame_count: 0, progress_seconds: 0,
  error_code: null, created_at: '2026-11-06T05:00:00Z', started_at: null, completed_at: null, ...extra,
});
const crossing = (id, seconds, direction = 'OUTSIDE_TO_INSIDE', gate = 'OPEN') => ({
  event_id: id, event_type: 'CROSSING_COMPLETED', track_id: 4, direction, source_zone: 'gate_approach',
  destination_zone: 'gate_interior', video_time_seconds: seconds, occurred_at: '2026-11-06T05:00:10Z',
  metadata: { gate_state: gate, sequence_number: 9 },
});
const mesh = (id, seconds, type, track = 7) => ({
  event_id: id, event_type: type, track_id: track, direction: null, source_zone: null, destination_zone: 'mesh_area',
  video_time_seconds: seconds, occurred_at: '2026-11-06T05:00:10Z', metadata: { zone: 'mesh_area' },
});

/** A scripted API plus a manual timer queue, so each polling cycle runs on demand. */
function harness(jobs, pages = []) {
  const calls = { job: 0, results: [] };
  const timers = [];
  let active = 0;
  let maxActive = 0;
  const updates = [];
  const step = async (list, index, fallback) => { const value = list[Math.min(index, list.length - 1)] ?? fallback; if (value instanceof Error) throw value; return value; };
  const api = {
    getJob: async () => { active += 1; maxActive = Math.max(maxActive, active); await null; active -= 1; return step(jobs, calls.job++); },
    getResults: async (_id, params) => { calls.results.push(params); return step(pages, calls.results.length - 1, { items: [], alerts: [], alerts_available: true }); },
    describeError: (error) => error.message,
  };
  const poller = createVideoJobPoller({
    jobId: 'job-1', api, onUpdate: (value) => updates.push(value), now: () => calls.job * 2000,
    setTimer: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimer: () => {},
  });
  return { poller, calls, timers, updates, maxActive: () => maxActive };
}

test('a saved job is read once and does not poll until processing starts', async () => {
  const { poller, timers, updates } = harness([job('UPLOADED')]);
  await poller.start();
  assert.equal(updates.at(-1).job.status, 'UPLOADED');
  assert.equal(timers.length, 0);
});

test('poller reads the job configuration when status omits its threshold', async () => {
  let received;
  const poller = createVideoJobPoller({
    jobId: 'job-1',
    api: {
      getJob: async () => job('UPLOADED'),
      getConfig: async () => ({ alert_configuration: { max_gate_open_seconds: 3 } }),
      getResults: async () => ({ items: [], transitions: [], alerts: [] }),
      describeError: String,
    },
    onUpdate: (state) => { received = state.job; },
  });
  await poller.start();
  poller.stop();
  assert.equal(received.alert_configuration.max_gate_open_seconds, 3);
});

test('poller publishes only the progress field from the results monitoring object', async () => {
  let received;
  const progress = 0.8244978822243475;
  const poller = createVideoJobPoller({
    jobId: 'job-1',
    api: {
      getJob: async () => job('PROCESSING'),
      getResults: async () => ({ monitoring: { progress, state: 'CLOSED', gate_state: 'CLOSED' }, items: [], transitions: [], alerts: [] }),
      describeError: String,
    },
    onUpdate: (value) => { received = value; },
  });
  await poller.start();
  assert.equal(received.monitoring.progress, progress);
  assert.equal(received.monitoring.state, 'CLOSED');
  assert.equal(received.monitoring.gate_state, 'CLOSED');
  poller.stop();
});

test('polling runs while active, then stops after a terminal status', async () => {
  const { poller, timers, updates, calls } = harness([job('PROCESSING'), job('PROCESSING', { frame_count: 50 }), job('COMPLETED', { frame_count: 90 })]);
  await poller.start();
  assert.equal(timers.length, 1);
  await timers[0].fn();
  assert.equal(timers.length, 2);
  await timers[1].fn();
  assert.equal(updates.at(-1).job.status, 'COMPLETED');
  assert.equal(timers.length, 2, 'no further poll is scheduled');
  assert.equal(calls.results.at(-1).offset, 0, 'a finished job is re-read completely');
});

test('failed and cancelled jobs also stop polling', async () => {
  for (const status of ['FAILED', 'CANCELLED']) {
    const { poller, timers, updates } = harness([job(status, { error_code: status === 'FAILED' ? 'VIDEO_PIPELINE_FAILED' : null })]);
    await poller.start();
    assert.equal(updates.at(-1).job.status, status);
    assert.equal(timers.length, 0);
  }
});

test('events seen in overlapping pages are never duplicated', async () => {
  const a = crossing('a', 1);
  const b = crossing('b', 2);
  const { poller, timers, updates } = harness([job('PROCESSING'), job('PROCESSING')], [
    { items: [a], alerts: [], alerts_available: true }, { items: [a, b], alerts: [], alerts_available: true },
  ]);
  await poller.start();
  await timers[0].fn();
  assert.deepEqual(updates.at(-1).events.map((event) => event.event_id), ['a', 'b']);
});

test('a network failure keeps last results, reports the error and retries with backoff', async () => {
  const a = crossing('a', 1);
  const { poller, timers, updates } = harness([job('PROCESSING'), new Error('Cannot reach the API.'), job('COMPLETED')], [{ items: [a], alerts: [], alerts_available: true }]);
  await poller.start();
  await timers[0].fn();
  assert.equal(updates.at(-1).error, 'Cannot reach the API.');
  assert.equal(updates.at(-1).events.length, 1);
  assert.equal(timers[1].ms, 4000);
  await timers[1].fn();
  assert.equal(updates.at(-1).error, '');
  assert.equal(updates.at(-1).job.status, 'COMPLETED');
});

test('a missing job reports not found and stops', async () => {
  const notFound = Object.assign(new Error('gone'), { response: { status: 404 } });
  const { poller, timers, updates } = harness([notFound]);
  await poller.start();
  assert.ok(updates.at(-1).notFound);
  assert.equal(timers.length, 0);
});

test('nothing is published after stop, so a switched job cannot overwrite the new one', async () => {
  const { poller, timers, updates } = harness([job('PROCESSING')]);
  const running = poller.start();
  poller.stop();
  await running;
  assert.equal(updates.length, 0);
  assert.equal(timers.length, 0);
});

test('a poke during a running cycle queues one more cycle instead of overlapping', async () => {
  const { poller, calls, maxActive, updates } = harness([job('UPLOADED'), job('PROCESSING')]);
  const first = poller.start();
  const second = poller.poke();
  await first; await second;
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(maxActive(), 1);
  assert.equal(calls.job, 2);
  assert.equal(updates.at(-1).job.status, 'PROCESSING');
});

test('eligibility follows backend status only', () => {
  assert.ok(jobCanStart(job('UPLOADED')));
  for (const status of ['QUEUED', 'PROCESSING', 'CANCEL_REQUESTED', 'COMPLETED', 'FAILED', 'CANCELLED']) assert.equal(jobCanStart(job(status)), false, status);
  assert.ok(jobIsActive(job('CANCEL_REQUESTED')));
  assert.ok(jobCanCancel(job('UPLOADED')) && !jobCanCancel(job('COMPLETED')));
});

test('upload validation mirrors the backend extension rule', () => {
  assert.equal(validateVideoFile({ name: 'GATE.MP4', size: 5 }), '');
  assert.equal(validateVideoFile({ name: 'gate.avi', size: 5 }), '');
  assert.match(validateVideoFile({ name: 'gate.webm', size: 5 }), /MP4 and AVI/);
  assert.match(validateVideoFile({ name: 'gate.mp4', size: 0 }), /empty/);
});

test('a template needs an assignment, a calibration and an enabled gate zone', () => {
  assert.equal(templateBlocker(null), '');
  assert.match(templateBlocker({ assignment: { id: 'a', calibration: null } }), /calibration/);
  const item = { assignment: { id: 'a', calibration: {} } };
  assert.match(templateBlocker(item, [{ zone_type: 'gate_leaf_roi', enabled: false }]), /gate_leaf_roi/);
  assert.equal(templateBlocker(item, [{ zone_type: 'gate_leaf_roi', enabled: true }]), '');
});

test('a video can be uploaded and processed without a camera assignment using its local zones and line', () => {
  const file = { name: 'gate.mp4', size: 12, lastModified: 34 };
  const key = `grill-gate-video-zones:${encodeURIComponent(file.name)}:${file.size}:${file.lastModified}:1920x1080`;
  const saved = {
    frame: { width: 1920, height: 1080 },
    zones: [{ id: 'gate_leaf_roi', zone_key: 'gate_leaf_roi', zone_type: 'gate_leaf_roi', enabled: true,
      polygon: [{ x: 0.2, y: 0.2 }, { x: 0.8, y: 0.2 }, { x: 0.8, y: 0.8 }, { x: 0.2, y: 0.8 }] }],
    line: { start: { x: 0.1, y: 0.5 }, end: { x: 0.9, y: 0.5 } },
  };
  const values = new Map([[key, JSON.stringify(saved)]]);
  const storage = { length: values.size, key: (index) => [...values.keys()][index], getItem: (name) => values.get(name) };
  const config = localVideoConfiguration(file, storage);
  assert.equal(config.calibration.reference_frame.width, 1920);
  assert.deepEqual(config.calibration.directional_crossing.line_start, saved.line.start);
  assert.equal(videoUploadConfiguration(null, [], file, storage).source, 'video');
  assert.equal(videoUploadConfiguration(null, [], file, {}).blocker.includes('no camera assignment'), true);
});

test('a video with required zones does not need a directional line or measured endpoints', () => {
  const file = { name: 'gate-no-line.mp4', size: 12, lastModified: 35 };
  const key = `grill-gate-video-zones:${encodeURIComponent(file.name)}:${file.size}:${file.lastModified}:1920x1080`;
  const saved = {
    frame: { width: 1920, height: 1080 },
    zones: [{ id: 'gate_leaf_roi', zone_key: 'gate_leaf_roi', zone_type: 'gate_leaf_roi', enabled: true,
      polygon: [{ x: 0.2, y: 0.2 }, { x: 0.8, y: 0.2 }, { x: 0.8, y: 0.8 }, { x: 0.2, y: 0.8 }] },
    { id: 'gate_approach', zone_key: 'gate_approach', zone_type: 'gate_approach', enabled: true,
      polygon: [{ x: 0.1, y: 0.1 }, { x: 0.2, y: 0.1 }, { x: 0.2, y: 0.2 }, { x: 0.1, y: 0.2 }] },
    { id: 'gate_interior', zone_key: 'gate_interior', zone_type: 'gate_interior', enabled: true,
      polygon: [{ x: 0.3, y: 0.3 }, { x: 0.4, y: 0.3 }, { x: 0.4, y: 0.4 }, { x: 0.3, y: 0.4 }] }],
  };
  const values = new Map([[key, JSON.stringify(saved)]]);
  const storage = { length: values.size, key: (index) => [...values.keys()][index], getItem: (name) => values.get(name) };
  const config = localVideoConfiguration(file, storage);
  assert.equal(config.calibration.directional_crossing, undefined);
  assert.equal(config.zones.length, 3);
  assert.equal(videoUploadConfiguration(null, [], file, storage).source, 'video');
});

test('video snapshot reports backend values and leaves unreported ones null', () => {
  const view = videoMonitoring({
    gateClassification: { sessionId: 'video:job-1', gateState: 'PARTIALLY_OPEN', direction: 'CLOSING' },
    job: job('PROCESSING', { progress_seconds: 30 }),
    events: [crossing('a', 10), crossing('b', 20, 'INSIDE_TO_OUTSIDE', 'PARTIALLY_OPEN'),
      mesh('m1', 5, 'MESH_PERSON_ENTERED', 1), mesh('m2', 6, 'MESH_PERSON_ENTERED', 2), mesh('m3', 8, 'MESH_PERSON_EXITED', 1)]
      .sort((x, y) => x.video_time_seconds - y.video_time_seconds),
    alerts: [
      { id: 'r', title: 'Old', source_event_type: 'MESH_OCCUPANCY_HIGH', severity: 'WARNING', status: 'RESOLVED', summary: 's', domain_data: {} },
      { id: 'o', title: 'Open', source_event_type: 'GATE_OPEN_TOO_LONG', severity: 'HIGH', status: 'OPEN', summary: 's', domain_data: { video_time_seconds: 12.5 } },
    ],
  });
  assert.equal(view.gateState, 'PARTIALLY_OPEN');
  assert.equal(view.gateStateTimeLabel, '');
  assert.equal(view.gateOpenSeconds, null);
  assert.equal(view.openWithoutCrossingSeconds, null);
  assert.equal(view.meshGatheringSeconds, null);
  assert.equal(view.secondsSinceCrossing, null, 'crossing age comes only from the authoritative timer snapshot');
  assert.deepEqual([view.entryCount, view.exitCount], [1, 1]);
  assert.equal(view.crossings[0].direction, 'EXIT', 'newest first');
  assert.equal(view.crossings[0].timeLabel, '00:20.0');
  assert.equal(view.meshPeopleCount, 1);
  assert.equal(view.activeAlertCount, 1);
  assert.equal(view.alerts[0].id, 'o', 'active alerts come first');
  assert.equal(view.alerts[0].timeLabel, '00:12.5');
});

test('video timer follows the video timeline and confirmed frontend gate state', () => {
  const open = videoMonitoring({ job: job('PROCESSING', {
    monitoring: { state: 'OPEN', video_timestamp: 12, open_without_crossing_seconds: 99 },
  }) , gateClassification: { gateState: 'FULLY_OPEN', gateOpenedAt: 9000, cycleStartedAt: 9000,
    timerTimebase: 'video', transitions: [{ toState: 'FULLY_OPEN', at: 9000, timebase: 'video' }] } });
  assert.equal(open.gateOpenSeconds, 3);
  assert.equal(open.openWithoutCrossingSeconds, 3);
  const unknown = videoMonitoring({ job: job('PROCESSING', {
    monitoring: { state: 'UNKNOWN', open_without_crossing_seconds: 9 },
  }) });
  assert.equal(unknown.openWithoutCrossingSeconds, null);
});

test('timer follows the same confirmed frontend gate state shown by the Gate State panel', () => {
  const view = videoMonitoring({
    job: job('PROCESSING', { monitoring: { state: 'CLOSED', progress: 0.10, direction: 'CLOSING' } }),
    monitoring: { progress: 0.85, state: 'CLOSED', gate_state: 'CLOSED' },
    transitions: [{ from_state: 'FULLY_OPEN', to_state: 'CLOSED', progress: 0.16 }],
    gateClassification: { sessionId: 'video:job-1', gateState: 'FULLY_OPEN', direction: 'OPENING' },
  });
  assert.equal(view.gateState, 'FULLY_OPEN');
  assert.equal(view.timerGateState, 'FULLY_OPEN');
  assert.equal(view.timerState, 'TIMER_UNAVAILABLE');
  assert.equal(view.gateDirection, 'OPENING');
});

test('video timer starts from the confirmed FULLY_OPEN state despite a stale backend state and resets at a crossing', () => {
  const openAt = 11.745;
  const crossingAt = 14.8;
  const view = videoMonitoring({
    job: job('PROCESSING', { monitoring: { state: 'FULLY_OPEN', gate_state: 'FULLY_OPEN', video_timestamp: 16.783,
      gate_open_seconds: 5.038, open_without_crossing_seconds: 2.002 } }),
    transitions: [{ from_state: 'PARTIALLY_OPEN', to_state: 'FULLY_OPEN', video_time_seconds: openAt }],
    events: [crossing('last-crossing', crossingAt)],
    gateClassification: { gateState: 'FULLY_OPEN', gateOpenedAt: openAt * 1000, cycleStartedAt: crossingAt * 1000,
      lastCrossingAt: crossingAt * 1000, timerTimebase: 'video' },
    now: 1000, receivedAt: 1000,
  });
  assert.equal(view.gateState, 'FULLY_OPEN');
  assert.equal(view.timerGateState, 'FULLY_OPEN');
  assert.equal(view.gateOpenSince, openAt);
  assert.ok(Math.abs(view.gateOpenSeconds - 5.038) < 0.001);
  assert.ok(Math.abs(view.openWithoutCrossingSeconds - 1.983) < 0.001);
  assert.equal(view.timerState, 'COUNTING');
});

test('video monitoring distinguishes configured, unset, unavailable and final timer data', () => {
  const configured = videoMonitoring({ job: job('PROCESSING', { monitoring: {
    state: 'OPEN', video_timestamp: 10, gate_open_seconds: 99, open_without_crossing_seconds: 99,
    open_without_crossing_threshold_seconds: 3, threshold_configured: true,
    progress_percent: 66.67, timer_state: 'COUNTING', source_timestamp: '2026-11-06T05:00:02Z',
  } }), gateClassification: { gateState: 'FULLY_OPEN', gateOpenedAt: 8000, cycleStartedAt: 8000,
    timerTimebase: 'video', transitions: [{ toState: 'FULLY_OPEN', at: 8000, timebase: 'video' }] } });
  assert.equal(configured.timerState, 'COUNTING');
  assert.equal(configured.timerProgressPercent, 66.67);
  assert.equal(configured.thresholdConfigured, true);
  const unset = videoMonitoring({ job: job('PROCESSING', { monitoring: {
    state: 'OPEN', open_without_crossing_seconds: 2, threshold_configured: false, timer_state: 'COUNTING',
  } }) });
  assert.equal(unset.thresholdConfigured, false);
  const missing = videoMonitoring({ job: job('PROCESSING', { monitoring: { state: 'OPEN' } }),
    gateClassification: { gateState: 'FULLY_OPEN' } });
  assert.equal(missing.timerState, 'TIMER_UNAVAILABLE');
  assert.notEqual(missing.timerState, 'NOT_COUNTING');
  const old = videoMonitoring({ job: job('COMPLETED') });
  assert.equal(old.finalTimer, true);
  assert.equal(old.timerRecorded, false);
  const finalClosed = videoMonitoring({ job: job('COMPLETED', { monitoring: {
    state: 'CLOSED', open_without_crossing_seconds: null, threshold_configured: false,
    timer_state: 'NOT_COUNTING', source_timestamp: '2026-11-06T05:00:02Z',
  } }), gateClassification: { gateState: 'CLOSED' } });
  assert.equal(finalClosed.timerRecorded, false, 'frontend timer references determine whether the cycle was recorded');
});

test('video monitoring uses the saved job threshold if an older status response omits it', () => {
  const view = videoMonitoring({ job: job('COMPLETED', {
    alert_configuration: { max_gate_open_seconds: 3 },
    monitoring: { state: 'OPEN' },
  }) });
  assert.equal(view.openWithoutCrossingThresholdSeconds, 3);
  assert.equal(view.thresholdConfigured, true);
  assert.equal(view.timerRecorded, false);
});

test('the crossing total counts every event even though the list is capped', () => {
  const events = Array.from({ length: 60 }, (_, index) => crossing(`c${index}`, index));
  const view = videoMonitoring({ job: job('COMPLETED'), events });
  assert.equal(view.crossingTotal, 60);
  assert.equal(view.crossings.length, 50);
  assert.equal(view.entryCount, 60);
});

test('an empty job shows no invented gate state or crossing timer', () => {
  const view = videoMonitoring({ job: job('PROCESSING') });
  assert.equal(view.gateState, 'UNKNOWN');
  assert.equal(view.secondsSinceCrossing, null);
  assert.equal(view.meshPeopleCount, 0);
  assert.deepEqual(view.crossings, []);
});

test('crossing panel explains when a saved job is missing crossing zones', () => {
  const view = videoMonitoring({ job: job('COMPLETED', { readiness: { crossing_zones_defined: false } }) });
  assert.equal(view.crossingConfigStatus, 'missing_required_zones');
});

test('progress is only reported when the backend supports it', () => {
  assert.equal(jobProgressPercent(job('PROCESSING', { frame_count: 500 })), null);
  assert.equal(jobProgressPercent(job('COMPLETED')), 100);
  assert.equal(processingFps(job('PROCESSING', { frame_count: 100 }), { frames: 50, at: 0 }, 2000), 25);
  assert.equal(processingFps(job('PROCESSING', { frame_count: 50 }), null, 2000), null);
  assert.equal(processingFps(job('COMPLETED', { frame_count: 100, started_at: '2026-11-06T05:00:00Z', completed_at: '2026-11-06T05:00:10Z' })), 10);
});

test('the timeline merges gate transitions with events, leaves out the end of the file and shows real values', () => {
  const view = videoMonitoring({
    gateClassification: { sessionId: 'video:job-1', gateState: 'PARTIALLY_OPEN' },
    job: job('PROCESSING', { progress: 0.42, monitoring: { state: 'OPENING', progress: 0.62, confidence: 0.91, gate_open_seconds: 3, mesh: { occupancy_count: 4 } } }),
    events: [crossing('a', 7.4)],
    transitions: [
      { sequence_number: 66, to_state: 'OPENING', video_time_seconds: 2.2 },
      { sequence_number: 153, to_state: 'OPEN', video_time_seconds: 5.1 },
      { sequence_number: 300, to_state: 'UNKNOWN', video_time_seconds: 10, reason: 'video ended' },
    ],
  });
  assert.deepEqual(view.events.map((row) => [row.timeLabel, row.title]), [
    ['00:07.4', 'Entry crossing · track #4'], ['00:05.1', 'Gate opened'], ['00:02.2', 'Gate opening started'],
  ]);
  assert.deepEqual([view.gateState, view.gateOpenSeconds, view.meshPeopleCount], ['PARTIALLY_OPEN', null, 4]);
  assert.equal('gateProgress' in view, false);
  assert.equal('gateConfidence' in view, false);
  assert.equal(jobPillLabel(job('PROCESSING', { progress: 0.42 })), 'PROCESSING 42%');
  assert.equal(jobPillLabel(null), 'NONE');
});

test('alert buttons follow locally stored Grill Gate statuses and retain evidence details', () => {
  const view = videoMonitoring({ job: job('COMPLETED'), alerts: [
    { id: 'o', status: 'OPEN', row_version: 3, allowed_actions: ['ACKNOWLEDGED', 'RESOLVED'],
      triggered_at: '2026-11-09T10:00:00Z', gate_open_duration_seconds: 12,
      configured_threshold_seconds: 10, evidence_refs: [{ type: 'snapshot', id: 'snap-1' }] },
    { id: 'a', status: 'ACKNOWLEDGED', row_version: 4, allowed_actions: ['RESOLVED'] },
  ] });
  assert.deepEqual(view.alerts.map((alert) => [alert.id, alert.version, alert.actions]), [
    ['o', 3, ['acknowledge', 'resolve']], ['a', 4, ['resolve']],
  ]);
  assert.equal(view.alerts[0].gateOpenDurationSeconds, 12);
  assert.equal(view.alerts[0].configuredThresholdSeconds, 10);
  assert.deepEqual(view.alerts[0].evidenceRefs, [{ type: 'snapshot', id: 'snap-1' }]);
  assert.match(view.alerts[0].timeLabel, /2026/);
});

test('event helpers', () => {
  assert.equal(formatVideoTime(72.42), '01:12.4');
  assert.equal(formatVideoTime(null), '—');
  const base = [crossing('a', 1)];
  assert.equal(mergeEvents(base, [crossing('a', 1)]), base);
  assert.deepEqual(mergeEvents(base, [crossing('c', 0.5)]).map((event) => event.event_id), ['c', 'a']);
});


test('open-without-crossing media duration never advances with browser time and freezes on completion', () => {
  const gateClassification = { sessionId: 'video:freeze', gateState: 'FULLY_OPEN',
    gateOpenedAt: 2000, cycleStartedAt: 2000, timerTimebase: 'video' };
  const view = (status, now) => videoMonitoring({
    job: job(status, { monitoring: { video_timestamp: 6, gate_open_seconds: 4 } }),
    gateClassification, receivedAt: 1000, now });
  assert.equal(view('PROCESSING', 1000).openWithoutCrossingSeconds, 4);
  assert.equal(view('PROCESSING', 999999).openWithoutCrossingSeconds, 4);
  assert.equal(view('COMPLETED', 999999).openWithoutCrossingSeconds, 4);
  assert.equal(view('COMPLETED', 1999999).openWithoutCrossingSeconds, 4);
});
