import test from 'node:test';
import assert from 'node:assert/strict';
import { createOpenTimerController } from './openTimerController.js';
const sample = { source: 'video', status: 'PROCESSING', gateSessionId: 'video:job', gateState: 'FULLY_OPEN',
  cycleStartedAt: 2000, openWithoutCrossingSeconds: 4, openWithoutCrossingThresholdSeconds: 4,
  videoTimeSeconds: 6, entryCount: 0, exitCount: 0 };
function harness(request = async () => ({ alert_raised: true })) {
  const states = new Map(), calls = []; let time = 0;
  const evaluate = createOpenTimerController({ read: (_, key) => states.get(key), write: (v) => states.set(v.cycleId, v),
    request: async (...args) => { calls.push(args); return request(...args); }, now: () => time });
  return { evaluate, states, calls, advance: (ms) => { time += ms; } };
}
for (const gateState of ['CLOSED', 'PARTIALLY_OPEN', 'UNKNOWN']) test(`${gateState} cannot request an alert`, async () => {
  const h = harness(); await h.evaluate({ ...sample, gateState }); assert.equal(h.calls.length, 0);
});
test('first threshold sample sends actual frontend elapsed and one request across repeated snapshots', async () => {
  const h = harness(); await h.evaluate({ ...sample, openWithoutCrossingSeconds: 3.9 });
  assert.equal(h.calls.length, 0);
  await Promise.all([h.evaluate(sample), h.evaluate(sample)]); await h.evaluate(sample);
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0][1].elapsed_seconds, 4);
  assert.equal(h.states.get('video:job:2000').status, 'ALERT_RAISED');
});
test('failure backs off and retries the same frozen payload and idempotency key', async () => {
  let fail = true; const h = harness(async () => { if (fail) throw Error('offline'); return { alert_raised: true }; });
  await h.evaluate(sample); await h.evaluate(sample); assert.equal(h.calls.length, 1);
  assert.equal(h.states.get('video:job:2000').status, 'ALERT_REQUEST_FAILED');
  fail = false; h.advance(1000); await h.evaluate({ ...sample, openWithoutCrossingSeconds: 8 });
  assert.deepEqual(h.calls[1][1], h.calls[0][1]);
});
test('new crossing and new job each own a separate cycle', async () => {
  const h = harness(); await h.evaluate(sample);
  await h.evaluate({ ...sample, cycleStartedAt: 6000 });
  await h.evaluate({ ...sample, gateSessionId: 'video:new' }); assert.equal(h.calls.length, 3);
});
test('final frame qualifies once; reopening the completed job cannot resend', async () => {
  const h = harness(); const final = { ...sample, status: 'COMPLETED', finalTimer: true };
  await h.evaluate({ ...sample, openWithoutCrossingSeconds: 3 });
  await h.evaluate(final); await h.evaluate(final); assert.equal(h.calls.length, 1);
});
test('disabled thresholds and inactive live monitoring do not trigger', async () => {
  const h = harness(); await h.evaluate({ ...sample, openWithoutCrossingThresholdSeconds: 0 });
  await h.evaluate({ ...sample, source: 'live', status: 'INACTIVE' }); assert.equal(h.calls.length, 0);
});
test('unconfirmed response stays failed until backend confirms', async () => {
  const h = harness(async () => ({ alert_raised: false })); await h.evaluate(sample);
  assert.equal(h.states.get('video:job:2000').status, 'ALERT_REQUEST_FAILED');
});

test('opening a completed video without an active frontend cycle cannot create a new alert', async () => {
  const h = harness(); await h.evaluate({ ...sample, status: 'COMPLETED', finalTimer: true });
  assert.equal(h.calls.length, 0);
});
