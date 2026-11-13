import test from 'node:test';
import assert from 'node:assert/strict';
import { availableStoredVideos } from './storageVideos.js';

test('sample and upload videos appear, evidence and non-videos do not', () => {
  const files = [
    { category: 'sample_videos', name: 'door.MP4' },
    { category: 'uploads', name: 'entry.avi' },
    { category: 'clips', name: 'evidence.mp4' },
    { category: 'uploads', name: 'notes.txt' },
  ];
  assert.deepEqual(availableStoredVideos(files, '.mp4,.avi').map((item) => item.name), ['door.MP4', 'entry.avi']);
  assert.deepEqual(availableStoredVideos(files, '.mp4').map((item) => item.name), ['door.MP4']);
});
