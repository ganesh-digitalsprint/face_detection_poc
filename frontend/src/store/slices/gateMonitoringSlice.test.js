import assert from 'node:assert/strict';
import { test } from 'node:test';
import reducer, {
  classifyGateProgress, restoreGateMonitoring, updateGateProgress,
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
