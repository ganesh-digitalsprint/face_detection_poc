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

test('open-without-crossing display derives from the confirmed frontend timer reference', () => {
  const start = Date.now() - 2500;
  const open = liveMonitoring({ gate: { state: 'UNKNOWN', open_without_crossing_seconds: 99 }, now: Date.now() }, {
    gateState: 'FULLY_OPEN', gateOpenedAt: start, cycleStartedAt: start, timerTimebase: 'wall',
    transitions: [{ toState: 'FULLY_OPEN', at: start, timebase: 'wall' }],
  });
  assert.ok(open.openWithoutCrossingSeconds >= 2.4 && open.openWithoutCrossingSeconds <= 2.6);
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
  }, { gateState: 'FULLY_OPEN', gateOpenedAt: start, cycleStartedAt: start + 10_000,
    timerTimebase: 'wall', transitions: [{ toState: 'FULLY_OPEN', at: start, timebase: 'wall' }],
    lastCrossingAt: start + 10_000 });
  assert.equal(snapshot.gateOpenSeconds, 15);
  assert.equal(snapshot.openWithoutCrossingSeconds, 5);
  assert.equal(snapshot.timerState, 'COUNTING');

  const noCrossing = liveMonitoring({
    now: start + 15_000,
    gate: { state: 'FULLY_OPEN', gate_open_since: '2026-11-10T10:00:00Z', timer_state: 'COUNTING' },
  }, { gateState: 'FULLY_OPEN', gateOpenedAt: start, cycleStartedAt: start, timerTimebase: 'wall',
    transitions: [{ toState: 'FULLY_OPEN', at: start, timebase: 'wall' }] });
  assert.equal(noCrossing.gateOpenSeconds, 15);
  assert.equal(noCrossing.openWithoutCrossingSeconds, 15);
});

test('live timer starts from confirmed FULLY_OPEN despite a stale backend state and resets on crossing', () => {
  const openedAt = Date.parse('2026-11-10T10:00:00Z');
  const crossedAt = openedAt + 10_000;
  const snapshot = liveMonitoring({ now: openedAt + 15_000,
    gate: { state: 'FULLY_OPEN', gate_state: 'FULLY_OPEN', gate_open_since: new Date(openedAt).toISOString(),
      last_crossing_at: new Date(crossedAt).toISOString() },
  }, { gateState: 'FULLY_OPEN', gateOpenedAt: openedAt, timerTimebase: 'wall' });
  assert.equal(snapshot.gateState, 'FULLY_OPEN');
  assert.equal(snapshot.timerGateState, 'FULLY_OPEN');
  assert.equal(snapshot.gateOpenSeconds, 15);
  assert.equal(snapshot.openWithoutCrossingSeconds, 5);
});

test('live frontend timer reports threshold reached and prefers the backend alert after it arrives', () => {
  const started = 10_000;
  const gateClassification = { gateState: 'FULLY_OPEN', gateOpenedAt: started, cycleStartedAt: started,
    timerTimebase: 'wall', transitions: [{ toState: 'FULLY_OPEN', at: started, timebase: 'wall' }] };
  const reached = liveMonitoring({ gate: { open_without_crossing_threshold_seconds: 4 }, now: started + 4000 }, gateClassification);
  assert.equal(reached.openWithoutCrossingSeconds, 4);
  assert.equal(reached.timerState, 'THRESHOLD_REACHED');
  const alerted = liveMonitoring({ gate: { open_without_crossing_threshold_seconds: 4 }, now: started + 5000,
    alerts: [{ id: 'alert-1', source_event_type: 'GATE_OPEN_TOO_LONG', status: 'OPEN' }] }, gateClassification);
  assert.equal(alerted.timerState, 'ALERT_RAISED');
});
