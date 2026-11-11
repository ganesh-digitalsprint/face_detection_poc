import assert from 'node:assert/strict';
import { test } from 'node:test';
import { liveMonitoring } from './liveMonitoringModel.js';

test('live alert monitoring carries the local API error detail to the Active Alerts panel', () => {
  const snapshot = liveMonitoring({ alertsAvailable: false,
    alertsError: 'Could not load this assignment’s local Grill Gate alerts (HTTP 503).' });
  assert.equal(snapshot.alertsAvailable, false);
  assert.equal(snapshot.alertsError, 'Could not load this assignment’s local Grill Gate alerts (HTTP 503).');
});

test('live alert monitoring distinguishes waiting, empty success, and an attempted request error', () => {
  const waiting = liveMonitoring({ alertsLoading: true, alertsRequestAttempted: false });
  assert.equal(waiting.alertsLoading, true);
  assert.equal(waiting.alertsRequestAttempted, false);
  const empty = liveMonitoring({ alerts: [], alertsAvailable: true, alertsRequestAttempted: true });
  assert.equal(empty.alertsAvailable, true);
  assert.equal(empty.activeAlertCount, 0);
  const failed = liveMonitoring({ alertsAvailable: false, alertsRequestAttempted: true, alertsError: 'HTTP 503' });
  assert.equal(failed.alertsAvailable, false);
  assert.equal(failed.alertsError, 'HTTP 503');
});

test('open-without-crossing display consumes the backend rule timer and contract states', () => {
  const open = liveMonitoring({ gate: { state: 'CLOSED', open_without_crossing_seconds: 2.5 } }, { gateState: 'FULLY_OPEN' });
  assert.equal(open.openWithoutCrossingSeconds, 2.5);
  assert.equal(open.timerState, 'COUNTING');
  const unknown = liveMonitoring({ gate: { state: 'FULLY_OPEN', open_without_crossing_seconds: 12 } }, { gateState: 'UNKNOWN' });
  assert.equal(unknown.openWithoutCrossingSeconds, null);
  const closed = liveMonitoring({ gate: { state: 'FULLY_OPEN', open_without_crossing_seconds: null } }, { gateState: 'CLOSED' });
  assert.equal(closed.openWithoutCrossingSeconds, null);
});

test('live full-open timers derive elapsed seconds from the confirmed episode timestamps', () => {
  const start = Date.parse('2026-11-10T10:00:00Z');
  const snapshot = liveMonitoring({
    now: start + 15_000,
    gate: {
      state: 'FULLY_OPEN', gate_open_since: '2026-11-10T10:00:00Z',
      last_crossing_at: '2026-11-10T10:00:10Z', gate_open_seconds: 0,
      open_without_crossing_seconds: 0,
    },
  }, { gateState: 'FULLY_OPEN' });
  assert.equal(snapshot.gateOpenSeconds, 15);
  assert.equal(snapshot.openWithoutCrossingSeconds, 5);
  assert.equal(snapshot.timerState, 'COUNTING');

  const noCrossing = liveMonitoring({
    now: start + 15_000,
    gate: { state: 'FULLY_OPEN', gate_open_since: '2026-11-10T10:00:00Z', timer_state: 'COUNTING' },
  }, { gateState: 'FULLY_OPEN' });
  assert.equal(noCrossing.gateOpenSeconds, 15);
  assert.equal(noCrossing.openWithoutCrossingSeconds, 15);
});
