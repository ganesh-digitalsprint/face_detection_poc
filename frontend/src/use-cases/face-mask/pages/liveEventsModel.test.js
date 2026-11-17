import test from 'node:test';
import assert from 'node:assert/strict';
import { incidentStatusForEvent, normalizeLiveEvents } from './liveEventsModel.js';
import { sourceMediaUrl } from '../../../api/sourceThumbnail.js';

test('live concealment events are deduplicated by source ID and sorted newest first', () => {
  const old = { id: 'old', first_seen: '2026-01-01T00:00:00Z' };
  const newest = { id: 'new', first_seen: '2026-01-02T00:00:00Z' };
  assert.deepEqual(normalizeLiveEvents([old, newest, { ...newest, camera_name: 'updated duplicate' }]), [newest, old]);
});

test('source review statuses map to the incident state shown in the list', () => {
  assert.equal(incidentStatusForEvent('OPEN'), 'OPEN');
  assert.equal(incidentStatusForEvent('UNDER_REVIEW'), 'ACKNOWLEDGED');
  assert.equal(incidentStatusForEvent('FALSE_POSITIVE'), 'DISMISSED');
  assert.equal(incidentStatusForEvent('CLOSED'), 'RESOLVED');
});

test('Face Mask snapshot paths resolve through the mounted snapshot URL', () => {
  assert.equal(sourceMediaUrl('http://face-mask', 'screenshots/face_mask/event.jpg', 'face_mask'), 'http://face-mask/storage/snapshots/event.jpg');
  assert.equal(sourceMediaUrl('http://face-mask', '../event.jpg', 'face_mask'), '');
});
