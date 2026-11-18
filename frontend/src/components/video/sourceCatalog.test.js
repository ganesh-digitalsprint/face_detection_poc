import assert from 'node:assert/strict';
import test from 'node:test';
import { filterSources, flattenSources, rememberSourceKey, savedSourceKey, sourceCatalog } from './sourceCatalog.js';

test('groups media, reuses a processed camera without duplicating the underlying file', () => {
  const groups = sourceCatalog({
    files: [{ path: 'sample_videos/door.mp4', category: 'sample_videos', name: 'door.mp4', size: 100 },
      { path: 'uploads/a.mp4', category: 'uploads', upload_id: 'up-1', name: 'a.mp4', size: 200 }],
    browse: [{ path: 'D:/storage/sample_videos/door.mp4', name: 'door.mp4' }, { path: 'upload:up-1', name: 'a.mp4' }],
    cameras: [{ id: 'cam-1', cam_type: 'folder', name: 'Video-1', source: 'D:/storage/sample_videos/door.mp4' },
      { id: 'cam-duplicate', cam_type: 'folder', name: 'Video-1 again', source: 'D:/storage/sample_videos/door.mp4' },
      { id: 'cam-2', cam_type: 'rtsp', name: 'Door camera', source: 'rtsp://localhost/live' }],
    statuses: { 'cam-1': { status: 'DONE' } },
  });
  assert.equal(groups.samples.length, 1);
  assert.equal(groups.samples[0].cameraId, 'cam-1');
  assert.equal(groups.samples[0].status, 'DONE');
  assert.equal(groups.uploads[0].id, 'upload:up-1');
  assert.equal(groups.cameras.length, 1);
  assert.deepEqual(flattenSources(filterSources(groups, 'door')).map((item) => item.name), ['Door camera', 'door.mp4']);
});

test('selection survives remount by stable media ID and stays separate per use case', () => {
  const values = new Map();
  const storage = { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
  rememberSourceKey(storage, 'face_mask', 'upload:stable-id');
  assert.equal(savedSourceKey(storage, 'face_mask'), 'upload:stable-id');
  assert.equal(savedSourceKey(storage, 'branch_exterior'), '');
  rememberSourceKey(storage, 'face_mask', '');
  assert.equal(savedSourceKey(storage, 'face_mask'), '');
});

test('a video keeps the active camera record so its edited Entry ROI is not lost', () => {
  const groups = sourceCatalog({
    files: [{ path: 'sample_videos/door.mp4', category: 'sample_videos', name: 'door.mp4' }],
    cameras: [
      { id: 'old', cam_type: 'folder', name: 'door', source: 'D:/storage/sample_videos/door.mp4' },
      { id: 'edited', cam_type: 'folder', name: 'door', source: 'sample_videos/door.mp4' },
    ],
    preferredCameraId: 'edited',
  });
  assert.equal(groups.samples[0].cameraId, 'edited');
});

test('uploaded videos are newest first, and unfinished uploads are not selectable', () => {
  const groups = sourceCatalog({ files: [
    { path: 'uploads/old.mp4', category: 'uploads', upload_id: 'old', name: 'old.mp4', modified: 100, upload_status: 'uploaded' },
    { path: 'uploads/new.mp4', category: 'uploads', upload_id: 'new', name: 'new.mp4', modified: 200, upload_status: 'uploaded' },
    { path: 'uploads/pending.mp4', category: 'uploads', upload_id: 'pending', name: 'pending.mp4', modified: 300, upload_status: 'queued' },
  ] });
  assert.deepEqual(groups.uploads.map((item) => item.id), ['upload:new', 'upload:old']);
});
