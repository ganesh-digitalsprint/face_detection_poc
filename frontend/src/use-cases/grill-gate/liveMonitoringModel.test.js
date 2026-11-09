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
  const open = liveMonitoring({ gate: { state: 'OPEN', open_without_crossing_seconds: 2.5 } });
  assert.equal(open.openWithoutCrossingSeconds, 2.5);
  assert.equal(open.timerState, 'NOT_COUNTING');
  const unknown = liveMonitoring({ gate: { state: 'UNKNOWN', open_without_crossing_seconds: 12 } });
  assert.equal(unknown.openWithoutCrossingSeconds, 12);
  const closed = liveMonitoring({ gate: { state: 'CLOSED', open_without_crossing_seconds: null } });
  assert.equal(closed.openWithoutCrossingSeconds, null);
});
