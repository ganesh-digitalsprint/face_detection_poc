import assert from 'node:assert/strict';
import { test } from 'node:test';
import { advanceVideoClock, elapsedSeconds, openWithoutCrossingSeconds, projectVideoClock } from './monitoringTimers.js';
import { liveMonitoring } from './liveMonitoringModel.js';

test('live timer uses its confirmed transition timestamp independently of API snapshots', () => {
  const openedAt = Date.parse('2026-11-11T10:00:00Z');
  const transitions = [{ toState: 'PARTIALLY_OPEN', at: openedAt - 2000, timebase: 'wall' },
    { toState: 'FULLY_OPEN', at: openedAt, timebase: 'wall' }];
  const snapshot = (now) => liveMonitoring({ gate: { open_without_crossing_seconds: 0 }, now }, {
    gateState: 'FULLY_OPEN', gateOpenedAt: openedAt, cycleStartedAt: openedAt,
    timerTimebase: 'wall', transitions,
  });
  assert.equal(snapshot(openedAt + 1000).gateOpenSeconds, 1);
  assert.equal(snapshot(openedAt + 10_000).gateOpenSeconds, 10);
  assert.equal(snapshot(openedAt + 10_000).openWithoutCrossingSeconds, 10);
});

test('crossing resets only the current interval and video time stays on its own timebase', () => {
  const openedAt = 1000;
  assert.equal(openWithoutCrossingSeconds({ gateState: 'FULLY_OPEN', openedAt, now: 5000 }), 4);
  assert.equal(openWithoutCrossingSeconds({ gateState: 'FULLY_OPEN', openedAt: 3000, now: 5000 }), 2);
  assert.equal(openWithoutCrossingSeconds({ gateState: 'PARTIALLY_OPEN', openedAt, now: 5000 }), null);
  assert.equal(projectVideoClock(12, 1000, 4000, true), 15_000);
  assert.equal(projectVideoClock(12, 1000, 4000, false), 12_000);
});

test('invalid or missing timer references never yield negative or NaN elapsed values', () => {
  assert.equal(elapsedSeconds(null, 1000), null);
  assert.equal(elapsedSeconds('invalid', 1000), null);
  assert.equal(openWithoutCrossingSeconds({ gateState: 'FULLY_OPEN', openedAt: 2000, now: 1000 }), 0);
});

test('video clock never moves backward when a poll trails the previous 1x projection', () => {
  const first = advanceVideoClock(null, null, 10, 1000);
  const second = advanceVideoClock(first, 1000, 11, 3000);
  const third = advanceVideoClock(second, 3000, 13, 5000);
  assert.equal(first, 10_000);
  assert.equal(second, 12_000, 'the stale 11 second poll cannot rewind the projected 12 second clock');
  assert.equal(third, 14_000, 'the next projection continues smoothly from the high-water mark');
});
