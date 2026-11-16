import assert from 'node:assert/strict';
import test from 'node:test';
import { playbackPlaceholder, playbackProgress, playbackStatus } from './playbackState.js';

test('legacy DONE is shown as FINISHED and stop wording points to picker', () => {
  assert.equal(playbackStatus('DONE'), 'FINISHED');
  assert.equal(playbackStatus('ONLINE', true), 'PROCESSING');
  assert.equal(playbackPlaceholder(true, 'FINISHED'), 'Finished — press Process video to run it again');
  assert.equal(playbackPlaceholder(false, 'STOPPED'), 'Pick a video above and press Process video');
});

test('file progress uses source frames and duration', () => {
  assert.deepEqual(playbackProgress({ frames_read: 42, frames_total: 134, source_fps: 1 }), { percent: 31, label: '00:42 / 02:14 · 31%' });
  assert.equal(playbackProgress({ frames_total: 0 }), null);
});
