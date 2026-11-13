import test from 'node:test';
import assert from 'node:assert/strict';
import { CHUNK_SIZE, MAX_SIZE, validateVideo } from './uploader.js';

test('uploader uses bounded chunks and validates size and extension', () => {
  assert.equal(CHUNK_SIZE, 8 * 1024 * 1024);
  assert.throws(() => validateVideo({ name: 'bad.exe', size: 8 }));
  assert.throws(() => validateVideo({ name: 'large.mp4', size: MAX_SIZE + 1 }));
  assert.doesNotThrow(() => validateVideo({ name: 'good.mkv', size: 8 }));
});
