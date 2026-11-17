import test from 'node:test';
import assert from 'node:assert/strict';
import { faceMaskAlertCenterLocation, faceMaskIncidentLocation } from './faceMaskAlertNavigation.js';

test('builds the Alert Center deep link from a Common incident UUID', () => {
  assert.equal(faceMaskIncidentLocation('d4a9e3e8-a47f-4a38-8c14-1ec23031b50c'),
    '/alerts?use_case=face_mask&alert_id=d4a9e3e8-a47f-4a38-8c14-1ec23031b50c');
});

test('does not treat a source event ID or malformed value as a Common incident ID', () => {
  assert.equal(faceMaskIncidentLocation('4388eae216ef49fb886017099ce56e17'), null);
  assert.equal(faceMaskIncidentLocation(undefined), null);
});

test('offers a Face Mask-filtered Alert Center link while publication is unavailable', () => {
  assert.equal(faceMaskAlertCenterLocation, '/alerts?use_case=face_mask');
});
