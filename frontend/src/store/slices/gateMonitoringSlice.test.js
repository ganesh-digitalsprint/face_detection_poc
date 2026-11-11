import assert from 'node:assert/strict';
import { test } from 'node:test';
import reducer, {
  gateSession, setOpenTimerRequest, classifyGateProgress, recordQualifyingCrossing, resetGateMonitoring, restoreGateMonitoring, updateCrossingCounts, updateGateProgress,
} from './gateMonitoringSlice.js';
import { projectPersistedGateMonitoring, restorePersistedGateMonitoring } from '../index.js';

const sessionId = 'video:job-a';
const start = (id = sessionId) => reducer(undefined, restoreGateMonitoring({ sessionId: id }));
const sample = (state, progress, observedAt, id = sessionId) => reducer(state,
  updateGateProgress({ sessionId: id, progress, observedAt }));

test('frontend classifier applies the configured three-state thresholds and hysteresis', () => {
  assert.equal(classifyGateProgress('CLOSED', 0.15), 'CLOSED');
  assert.equal(classifyGateProgress('CLOSED', 0.25), 'PARTIALLY_OPEN');
  assert.equal(classifyGateProgress('PARTIALLY_OPEN', 0.22), 'PARTIALLY_OPEN');
  assert.equal(classifyGateProgress('PARTIALLY_OPEN', 0.80), 'FULLY_OPEN');
  assert.equal(classifyGateProgress('FULLY_OPEN', 0.78), 'FULLY_OPEN');
  assert.equal(classifyGateProgress('FULLY_OPEN', 0.74), 'PARTIALLY_OPEN');
  assert.equal(classifyGateProgress('PARTIALLY_OPEN', 0.19), 'CLOSED');
  assert.equal(classifyGateProgress('FULLY_OPEN', 0.19), 'CLOSED');
});

test('Redux confirms one state change only after the candidate persists for 200 ms', () => {
  let state = start();
  state = sample(state, 0.10, 0);
  assert.equal(state.gateState, 'UNKNOWN');
  state = sample(state, 0.10, 200);
  assert.equal(state.gateState, 'CLOSED');
  assert.equal(state.transitions.length, 1);

  state = sample(state, 0.25, 300);
  assert.equal(state.gateState, 'CLOSED');
  state = sample(state, 0.30, 500);
  assert.equal(state.gateState, 'PARTIALLY_OPEN');
  assert.equal(state.direction, 'OPENING');
  state = sample(state, 0.30, 700);
  assert.equal(state.transitions.length, 2, 'repeated same-state samples do not duplicate history');

  state = sample(state, 0.80, 800);
  state = sample(state, 0.85, 1000);
  assert.equal(state.gateState, 'FULLY_OPEN');
  assert.equal(state.direction, 'OPENING');
  assert.equal(state.gateOpenedAt, 1000, 'timer starts at the confirmed FULLY_OPEN transition');
  assert.equal(state.cycleStartedAt, 1000);
});

test('timer remains stopped while PARTIALLY_OPEN and duplicate confirmed states do not restart it', () => {
  let state = start();
  state = sample(state, 0.3, 0);
  state = sample(state, 0.3, 200);
  assert.equal(state.gateState, 'PARTIALLY_OPEN');
  assert.equal(state.gateOpenedAt, null);
  state = sample(state, 0.85, 300);
  state = sample(state, 0.85, 500);
  assert.equal(state.gateOpenedAt, 500);
  state = sample(state, 0.9, 1000);
  assert.equal(state.gateOpenedAt, 500);
});

test('a completed crossing resets once per event id while the gate is fully open', () => {
  let state = start();
  state = sample(state, 0.1, 0);
  state = sample(state, 0.1, 200);
  state = sample(state, 0.3, 300);
  state = sample(state, 0.3, 500);
  state = sample(state, 0.9, 600);
  state = sample(state, 0.9, 800);
  state = reducer(state, recordQualifyingCrossing({ sessionId, eventId: 'cross-1', at: 1200 }));
  assert.equal(state.cycleStartedAt, 1200);
  state = reducer(state, recordQualifyingCrossing({ sessionId, eventId: 'cross-1', at: 1400 }));
  assert.equal(state.cycleStartedAt, 1200, 'duplicate polling of the same crossing cannot reset again');
  state = reducer(state, recordQualifyingCrossing({ sessionId, eventId: 'older-cross', at: 1100 }));
  assert.equal(state.cycleStartedAt, 1200, 'an out-of-order event cannot move the timer backward');
  state = reducer(state, recordQualifyingCrossing({ sessionId, eventId: 'cross-2', at: 1800 }));
  assert.equal(state.cycleStartedAt, 1800);
  state = sample(state, 0.7, 1900);
  state = sample(state, 0.7, 2100);
  assert.equal(state.gateState, 'PARTIALLY_OPEN');
  assert.equal(state.gateOpenedAt, null, 'leaving FULLY_OPEN stops the timer');
  state = reducer(state, recordQualifyingCrossing({ sessionId, eventId: 'cross-3', at: 2200 }));
  assert.equal(state.cycleStartedAt, null, 'crossings outside FULLY_OPEN do not start a cycle');
});

test('entry and exit count increases reset the open-without-crossing timer once', () => {
  let state = start();
  state = sample(state, 0.1, 0);
  state = sample(state, 0.1, 200);
  state = sample(state, 0.9, 300);
  state = sample(state, 0.9, 500);
  state = sample(state, 0.9, 700);
  state = sample(state, 0.9, 900);
  assert.equal(state.gateState, 'FULLY_OPEN');
  assert.equal(state.cycleStartedAt, 900);
  const counts = (entryCount, exitCount, observedAt) => updateCrossingCounts({
    sessionId, entryCount, exitCount, observedAt, timebase: 'wall',
  });
  state = reducer(state, counts(2, 0, 1000));
  assert.equal(state.cycleStartedAt, 900, 'the initial count snapshot establishes a baseline');
  state = reducer(state, counts(3, 0, 1100));
  assert.equal(state.cycleStartedAt, 1100, 'an ENTRY count increase resets the timer');
  state = reducer(state, counts(3, 0, 1200));
  assert.equal(state.cycleStartedAt, 1100, 'unchanged counts never reset the timer');
  state = reducer(state, counts(3, 1, 1300));
  assert.equal(state.cycleStartedAt, 1300, 'an EXIT count increase resets the timer');
});

test('starting a video processing run clears its prior gate timer and crossing-count baseline', () => {
  let state = start();
  state = sample(state, 0.1, 0);
  state = sample(state, 0.1, 200);
  state = sample(state, 0.9, 300);
  state = sample(state, 0.9, 500);
  state = sample(state, 0.9, 700);
  state = sample(state, 0.9, 900);
  state = reducer(state, updateCrossingCounts({ sessionId, entryCount: 3, exitCount: 1, observedAt: 1000 }));
  state = reducer(state, updateCrossingCounts({ sessionId, entryCount: 4, exitCount: 1, observedAt: 1200 }));
  assert.equal(state.gateState, 'FULLY_OPEN');
  assert.equal(state.cycleStartedAt, 1200);

  state = reducer(state, resetGateMonitoring({ sessionId }));
  assert.equal(state.gateState, 'UNKNOWN');
  assert.equal(state.gateOpenedAt, null);
  assert.equal(state.cycleStartedAt, null);
  assert.equal(state.lastEntryCount, null);
  assert.equal(state.lastExitCount, null);
});

test('candidate oscillation cancels confirmation and a new candidate starts a fresh dwell', () => {
  let state = start();
  state = sample(state, 0.10, 0);
  state = sample(state, 0.10, 200);
  state = sample(state, 0.30, 300);
  assert.equal(state.candidateState, 'PARTIALLY_OPEN');
  state = sample(state, 0.24, 350);
  assert.equal(state.candidateState, null);
  assert.equal(state.gateState, 'CLOSED');
  state = sample(state, 0.30, 400);
  state = sample(state, 0.30, 599);
  assert.equal(state.gateState, 'CLOSED');
  state = sample(state, 0.30, 600);
  assert.equal(state.gateState, 'PARTIALLY_OPEN');
});

test('a candidate timer restarts when uploaded-video samples switch from wall time to media time', () => {
  let state = start();
  state = reducer(state, updateGateProgress({ sessionId, progress: 0.9, observedAt: 1_800_000_000_000, timebase: 'wall' }));
  assert.equal(state.candidateState, 'FULLY_OPEN');
  state = reducer(state, updateGateProgress({ sessionId, progress: 0.9, observedAt: 5000, timebase: 'video' }));
  assert.equal(state.gateState, 'UNKNOWN');
  assert.equal(state.candidateSince, 5000);
  state = reducer(state, updateGateProgress({ sessionId, progress: 0.9, observedAt: 5200, timebase: 'video' }));
  assert.equal(state.gateState, 'FULLY_OPEN');
  assert.equal(state.gateOpenedAt, 5200);
  assert.equal(state.timerTimebase, 'video');
});

test('null and invalid progress preserve state and last valid progress without transitions', () => {
  let state = start();
  state = sample(state, 0.90, 0);
  state = sample(state, 0.90, 200);
  const transitionsBefore = state.transitions;
  const lastValid = state.lastValidProgress;
  for (const invalid of [null, undefined, NaN, Infinity, -Infinity, '0.4', -0.01, 1.01]) {
    state = sample(state, invalid, 300);
    assert.equal(state.gateState, 'FULLY_OPEN');
    assert.equal(state.lastValidProgress, lastValid);
    assert.equal(state.currentProgress, null);
    assert.equal(state.measurementAvailable, false);
    assert.equal(state.transitions, transitionsBefore);
    assert.equal(state.candidateState, null);
  }
});

test('persistence restores the same video session and resets state for a different job', () => {
  let state = start();
  state = sample(state, 0.10, 0);
  state = sample(state, 0.10, 200);
  state = sample(state, 0.90, 300);
  state = sample(state, 0.90, 500);
  state = sample(state, 0.90, 600);
  state = sample(state, 0.90, 800);

  const persisted = projectPersistedGateMonitoring(state);
  assert.equal('currentProgress' in persisted, false);
  assert.equal('measurementAvailable' in persisted, false);
  assert.equal('candidateState' in persisted, false);
  const restored = restorePersistedGateMonitoring(persisted);
  assert.equal(restored.sessionId, sessionId);
  assert.equal(restored.gateState, 'FULLY_OPEN');
  assert.equal(restored.lastValidProgress, 0.90);
  assert.equal(restored.measurementAvailable, false);
  assert.equal(restored.gateOpenedAt, 800);
  assert.equal(restored.cycleStartedAt, 800);
  assert.equal(restored.timerTimebase, 'wall');

  const differentJob = reducer(restored, restoreGateMonitoring({ sessionId: 'video:job-b' }));
  assert.equal(differentJob.sessionId, 'video:job-b');
  assert.equal(differentJob.gateState, 'UNKNOWN');
  assert.equal(differentJob.lastValidProgress, null);
});

test('an inactive session cannot update the selected job state', () => {
  let state = start('video:active');
  state = sample(state, 0.90, 0, 'video:other');
  assert.equal(state.gateState, 'UNKNOWN');
  assert.equal(state.lastValidProgress, null);
});


test('background sessions preserve cycle and request confirmation through navigation and persistence', () => {
  let state = sample(sample(start(), 0.9, 1000), 0.9, 1200);
  state = reducer(state, setOpenTimerRequest({ sessionId, cycleId: `${sessionId}:1200`, status: 'ALERT_RAISED' }));
  state = reducer(state, restoreGateMonitoring({ sessionId: 'live:camera' }));
  state = reducer(state, updateGateProgress({ sessionId, progress: 0.9, observedAt: 5000 }));
  assert.equal(gateSession(state, sessionId).cycleStartedAt, 1200);
  state = restorePersistedGateMonitoring(projectPersistedGateMonitoring(state));
  state = reducer(state, restoreGateMonitoring({ sessionId }));
  assert.equal(state.cycleStartedAt, 1200);
  assert.equal(state.alertRequests[`${sessionId}:1200`].status, 'ALERT_RAISED');
});
