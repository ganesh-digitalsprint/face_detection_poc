import test from 'node:test';
import assert from 'node:assert/strict';
import reducer, { restoreGateMonitoring, updateGateProgress, updateCrossingCounts,
  updateVideoTimerSample, setOpenTimerRequest, gateSession, resetGateMonitoring } from '../../store/slices/gateMonitoringSlice.js';
import { projectPersistedGateMonitoring, restorePersistedGateMonitoring } from '../../store/index.js';
import { processedVideoTimestamp } from './videoTimerClock.js';
import { videoMonitoring } from './videoJobModel.js';
import { liveMonitoring } from './liveMonitoringModel.js';
import { createOpenTimerController } from './openTimerController.js';

const sessionId = 'video:footage';
function opened() {
  let state = reducer(undefined, restoreGateMonitoring({ sessionId }));
  state = reducer(state, updateGateProgress({ sessionId, progress: 0.9, observedAt: 9800, timebase: 'video' }));
  state = reducer(state, updateGateProgress({ sessionId, progress: 0.9, observedAt: 10000, timebase: 'video' }));
  state = reducer(state, updateCrossingCounts({ sessionId, entryCount: 0, exitCount: 0, observedAt: 10000, timebase: 'video' }));
  return reducer(state, updateVideoTimerSample({ sessionId, timestampSeconds: 10, status: 'PROCESSING' }));
}
function view(state, overrides = {}) {
  return videoMonitoring({ job: { job_id: 'footage', status: state.videoProcessingStatus ?? 'PROCESSING',
    alert_configuration: { max_gate_open_seconds: 4 } }, gateClassification: state, ...overrides });
}
const frame = (state, seconds, status = 'PROCESSING') => reducer(state,
  updateVideoTimerSample({ sessionId, timestampSeconds: seconds, status }));

test('four seconds of footage produce four seconds regardless of CPU time or polling delay', () => {
  const state = frame(opened(), 14);
  for (const now of [0, 20000, 3600000]) {
    const m = view(state, { now, receivedAt: 0, videoClockBaseMs: 999000 });
    assert.equal(m.openWithoutCrossingSeconds, 4);
    assert.equal(m.gateOpenSeconds, 4);
    assert.equal(m.videoTimeSeconds, 14);
    assert.equal(m.timerNow, 14000);
  }
});

test('skipped frames jump by their exact footage duration without interpolation', () => {
  let state = frame(opened(), 12);
  assert.equal(view(state).openWithoutCrossingSeconds, 2);
  assert.equal(view(state).gateOpenSeconds, 2);
  state = frame(state, 14.5);
  assert.equal(view(state).openWithoutCrossingSeconds, 4.5);
  assert.equal(view(state).gateOpenSeconds, 4.5);
  assert.equal(view(state, { now: 1000000 }).openWithoutCrossingSeconds, 4.5);
});

for (const direction of ['ENTRY', 'EXIT']) test(`${direction} resets at event time rather than later poll time`, () => {
  let state = frame(opened(), 16);
  state = reducer(state, updateCrossingCounts({ sessionId, entryCount: direction === 'ENTRY' ? 1 : 0,
    exitCount: direction === 'EXIT' ? 1 : 0, entryCrossingAt: direction === 'ENTRY' ? 14500 : null,
    exitCrossingAt: direction === 'EXIT' ? 14500 : null, observedAt: 16000, timebase: 'video' }));
  assert.equal(state.cycleStartedAt, 14500);
  assert.equal(view(state).openWithoutCrossingSeconds, 1.5);
  assert.equal(view(state).gateOpenSeconds, 6);
  assert.equal(view(state, { now: 1000000 }).secondsSinceCrossing, 1.5);
  const repeated = reducer(state, updateCrossingCounts({ sessionId, entryCount: state.lastEntryCount,
    exitCount: state.lastExitCount, observedAt: 18000, timebase: 'video' }));
  assert.equal(repeated.cycleStartedAt, 14500);
  const decreased = reducer(repeated, updateCrossingCounts({ sessionId, entryCount: 0, exitCount: 0,
    observedAt: 18000, timebase: 'video' }));
  assert.equal(decreased.cycleStartedAt, 14500);
});

test('missing event timestamp resets at current processed timestamp; no crossing baseline is fabricated', () => {
  let state = opened();
  assert.equal(view(state).secondsSinceCrossing, null);
  state = reducer(state, updateCrossingCounts({ sessionId, entryCount: 1, exitCount: 0,
    observedAt: 14000, timebase: 'video' }));
  assert.equal(state.cycleStartedAt, 14000);
  state = frame(state, 14);
  assert.equal(view(state).openWithoutCrossingSeconds, 0);
});

for (const progress of [0.1, 0.5]) test(`confirmed progress ${progress} stops the timer`, () => {
  let state = opened();
  for (const observedAt of [15000, 15300]) state = reducer(state,
    updateGateProgress({ sessionId, progress, observedAt, timebase: 'video' }));
  assert.equal(view(state).openWithoutCrossingSeconds, null);
  assert.equal(state.cycleStartedAt, null);
});

for (const status of ['COMPLETED', 'FAILED', 'CANCELLED']) test(`${status} freezes the last valid sample even if the final timestamp is absent`, () => {
  let state = frame(opened(), 14.5);
  state = frame(state, undefined, status);
  state = frame(state, 90, 'PROCESSING');
  assert.equal(view(state).openWithoutCrossingSeconds, 4.5);
  assert.equal(view(state).gateOpenSeconds, 4.5);
  assert.equal(view(state).finalTimer, true);
  assert.equal(state.videoProcessingStatus, status);
  state = restorePersistedGateMonitoring(projectPersistedGateMonitoring(state));
  state = reducer(state, restoreGateMonitoring({ sessionId: 'live:other' }));
  state = reducer(state, restoreGateMonitoring({ sessionId }));
  assert.equal(view(state).openWithoutCrossingSeconds, 4.5);
  assert.equal(view(state).gateOpenSeconds, 4.5);
  assert.equal(view(state).finalTimer, true);
});

test('threshold jump sends actual elapsed, timestamp and cycle exactly once; final frame is evaluated', async () => {
  let state = opened(); const payloads = [];
  const options = { read: (_, key) => state.alertRequests[key],
    write: (value) => { state = reducer(state, setOpenTimerRequest(value)); },
    request: async (_, payload) => { payloads.push(payload); return { alert_raised: true, alert_id: 'persisted' }; } };
  const evaluate = createOpenTimerController(options);
  state = frame(state, 13.5); await evaluate(view(state));
  assert.equal(payloads.length, 0);
  state = frame(state, 15.2, 'COMPLETED');
  await Promise.all([evaluate(view(state)), evaluate(view(state))]);
  assert.equal(payloads.length, 1);
  assert.ok(Math.abs(payloads[0].elapsed_seconds - 5.2) < 0.000001);
  assert.equal(payloads[0].video_timestamp_seconds, 15.2);
  assert.equal(payloads[0].threshold_seconds, 4);
  assert.equal(payloads[0].timer_cycle_id, `${sessionId}:10000`);
  assert.equal(payloads[0].gate_state, 'FULLY_OPEN');
  assert.equal(state.alertRequests[`${sessionId}:10000`].status, 'ALERT_RAISED');
  state = restorePersistedGateMonitoring(projectPersistedGateMonitoring(state));
  await createOpenTimerController(options)(view(state));
  assert.equal(payloads.length, 1, 'reopening after refresh cannot resend confirmation');
});

test('new uploaded session has no old timer sample or crossing baseline', () => {
  const root = reducer(frame(opened(), 18, 'COMPLETED'), resetGateMonitoring({ sessionId: 'video:new' }));
  const state = gateSession(root, 'video:new');
  assert.equal(state.videoTimestampSeconds, null);
  assert.equal(state.cycleStartedAt, null);
  assert.equal(state.lastEntryCount, null);
});

test('timestamp normalization accepts seconds or source frame index divided by source FPS only', () => {
  assert.equal(processedVideoTimestamp({ monitoring: { video_timestamp: 12.5 } }), 12.5);
  assert.equal(processedVideoTimestamp({ monitoring: { frame_index: 300 }, job: { fps: 25, processing_fps: 2 } }), 12);
  for (const fps of [undefined, null, 0, -1, NaN, Infinity]) {
    assert.equal(processedVideoTimestamp({ monitoring: { frame_index: 300 }, job: { fps, processing_fps: 25 } }), null);
  }
  for (const video_timestamp of [-1, NaN, Infinity, '12.5']) {
    assert.equal(processedVideoTimestamp({ monitoring: { video_timestamp }, job: { video_time_seconds: 50 } }), null);
  }
  assert.equal(processedVideoTimestamp({ job: { frame_count: 300, processing_fps: 25 } }), null);
  assert.equal(processedVideoTimestamp({}), null);
  assert.equal(processedVideoTimestamp({ monitoring: { video_timestamp: null }, job: { video_time_seconds: 50 } }), null,
    'a missing processed timestamp must not fall through to decoder progress');
});

test('invalid samples cannot regress or fabricate video progress', () => {
  let state = frame(opened(), 14);
  for (const seconds of [NaN, Infinity, -1, undefined, 12]) state = frame(state, seconds);
  assert.equal(view(state).openWithoutCrossingSeconds, 4);
  const unrecorded = view({ gateState: 'FULLY_OPEN', timerTimebase: 'video', cycleStartedAt: 10000 },
    { job: { status: 'PROCESSING' }, monitoring: { video_timestamp: NaN } });
  assert.equal(unrecorded.openWithoutCrossingSeconds, null);
});

test('backend timer/history never starts an Open Without Crossing cycle before Redux confirmation', () => {
  const m = videoMonitoring({ job: { status: 'PROCESSING' }, monitoring: { video_timestamp: 15,
    gate_open_seconds: 10, open_without_crossing_seconds: 10 },
    gateClassification: { gateState: 'FULLY_OPEN' },
    transitions: [{ to_state: 'FULLY_OPEN', video_time_seconds: 5 }] });
  assert.equal(m.openWithoutCrossingSeconds, null);
});

test('live monitoring continues to advance by wall-clock seconds', () => {
  const classification = { gateState: 'FULLY_OPEN', timerTimebase: 'wall', gateOpenedAt: 10000, cycleStartedAt: 10000 };
  for (const seconds of [1, 2, 3, 4]) {
    assert.equal(liveMonitoring({ now: 10000 + seconds * 1000 }, classification).openWithoutCrossingSeconds, seconds);
  }
});


test('a crossing cycle discovered on the last active frame can qualify before finalization', async () => {
  let state = frame(opened(), 13);
  const sent = [];
  const evaluate = createOpenTimerController({ read: (_, key) => state.alertRequests[key],
    write: (v) => { state = reducer(state, setOpenTimerRequest(v)); },
    request: async (_, payload) => { sent.push(payload); return { alert_raised: true }; } });
  await evaluate(view(state));
  state = reducer(state, updateCrossingCounts({ sessionId, entryCount: 1, exitCount: 0,
    observedAt: 20000, entryCrossingAt: 15000, timebase: 'video' }));
  state = frame(state, 20);
  await evaluate(view(state));
  state = frame(state, 20, 'COMPLETED');
  await evaluate(view(state));
  assert.equal(sent.length, 1);
  assert.equal(sent[0].timer_cycle_id, `${sessionId}:15000`);
  assert.equal(sent[0].elapsed_seconds, 5);
  assert.equal(view(state).finalTimer, true);
});


test('gate opened at 10, crossing at 25, processed frame at 30 yields independent 20/5 durations', () => {
  let state = opened();
  state = reducer(state, updateCrossingCounts({ sessionId, entryCount: 1, exitCount: 0,
    observedAt: 30000, entryCrossingAt: 25000, timebase: 'video' }));
  state = frame(state, 30);
  assert.equal(view(state).gateOpenSeconds, 20);
  assert.equal(view(state).openWithoutCrossingSeconds, 5);
  assert.equal(state.gateOpenedAt, 10000);
  assert.equal(state.cycleStartedAt, 25000);
});

for (const progress of [0.1, 0.5]) test(`video Gate Open stops at the confirmed transition for progress ${progress}`, () => {
  let state = frame(opened(), 12);
  for (const observedAt of [15000, 15300]) state = reducer(state,
    updateGateProgress({ sessionId, progress, observedAt, timebase: 'video' }));
  state = frame(state, 20);
  assert.equal(view(state).gateOpenSeconds, 5.3);
  assert.equal(view(state).openWithoutCrossingSeconds, null);
  state = restorePersistedGateMonitoring(projectPersistedGateMonitoring(state));
  state = reducer(state, restoreGateMonitoring({ sessionId: 'live:other' }));
  state = reducer(state, restoreGateMonitoring({ sessionId }));
  assert.equal(view(state).gateOpenSeconds, 5.3);
  for (const observedAt of [24000, 24300]) state = reducer(state,
    updateGateProgress({ sessionId, progress: 0.5, observedAt, timebase: 'video' }));
  for (const observedAt of [25000, 25300]) state = reducer(state,
    updateGateProgress({ sessionId, progress: 0.9, observedAt, timebase: 'video' }));
  state = frame(state, 26);
  assert.equal(view(state).gateOpenSeconds, 0.7);
  assert.equal(view(state).openWithoutCrossingSeconds, 0.7);
});

test('out-of-order samples cannot move either video timer or the classification backward', () => {
  let state = frame(opened(), 14);
  state = reducer(state, updateGateProgress({ sessionId, progress: 0.1, observedAt: 11000, timebase: 'video' }));
  state = frame(state, 11);
  assert.equal(state.gateState, 'FULLY_OPEN');
  assert.equal(view(state).gateOpenSeconds, 4);
  assert.equal(view(state).openWithoutCrossingSeconds, 4);
});

test('terminal video responses cannot restart either gate cycle', () => {
  let state = frame(opened(), 14, 'COMPLETED');
  for (const [observedAt, progress] of [[15000, 0.1], [15300, 0.1], [20000, 0.9], [20300, 0.9]]) {
    state = reducer(state, updateGateProgress({ sessionId, progress, observedAt, timebase: 'video' }));
  }
  state = reducer(state, updateCrossingCounts({ sessionId, entryCount: 1, exitCount: 1,
    observedAt: 21000, timebase: 'video' }));
  assert.equal(state.gateOpenedAt, 10000);
  assert.equal(state.cycleStartedAt, 10000);
  assert.equal(view(state).gateOpenSeconds, 4);
  assert.equal(view(state).openWithoutCrossingSeconds, 4);
});

test('Gate Open stays unavailable without a valid processed timestamp or confirmed frontend start', () => {
  const job = { status: 'PROCESSING', monitoring: { video_timestamp: null, gate_open_seconds: 99 } };
  const m = videoMonitoring({ job, gateClassification: { gateState: 'FULLY_OPEN', gateOpenedAt: 10000, timerTimebase: 'video' } });
  assert.equal(m.gateOpenSeconds, null);
  assert.equal(m.openWithoutCrossingSeconds, null);
  const withoutStart = videoMonitoring({ job: { status: 'PROCESSING', video_time_seconds: 20 },
    gateClassification: { gateState: 'FULLY_OPEN' },
    transitions: [{ to_state: 'FULLY_OPEN', video_time_seconds: 10 }] });
  assert.equal(withoutStart.gateOpenSeconds, null);
});
