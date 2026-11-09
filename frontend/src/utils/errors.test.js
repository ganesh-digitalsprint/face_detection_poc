import test from 'node:test';
import assert from 'node:assert/strict';
import { describeError } from './errors.js';

test('describeError shows backend readiness reasons from structured validation details', () => {
  const error = { response: { status: 422, data: { detail: {
    code: 'ZONE_CONFIGURATION_NOT_READY',
    missing: [
      { item: 'gate_zone_defined', message: 'Draw an enabled Sliding gate leaf zone' },
      { item: 'calibration_matches_frame', message: 'Save a calibration that matches this video frame' },
    ],
  } } } };
  assert.equal(describeError(error).message,
    'Draw an enabled Sliding gate leaf zone; Save a calibration that matches this video frame');
});
