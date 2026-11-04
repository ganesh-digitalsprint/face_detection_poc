import assert from 'node:assert/strict';
import test from 'node:test';
import { NUMERIC, settingsErrors } from './faceMaskSettingsModel.js';

const valid = () => ({
  processing_fps: '6', clip_pre_seconds: '5', clip_post_seconds: '5', cooldown_seconds: '10', visibility_threshold: '0.6',
  frames_to_confirm: '5', confirm_window: '8', person_confidence: '0.4', entering_window_frames: '10',
  entering_min_displacement_px: '12', min_head_height_px: '48', min_sharpness: '60', min_brightness: '40',
  max_brightness: '230', max_yaw_degrees: '50',
});

test('every numeric field has a default in the valid fixture and no errors', () => {
  assert.deepEqual(NUMERIC.map(([k]) => k).filter((k) => !(k in valid())), []);
  assert.deepEqual(settingsErrors(valid()), {});
});

test('out of range, empty and non-numeric values are rejected', () => {
  assert.match(settingsErrors({ ...valid(), processing_fps: '0' }).processing_fps, /between 1 and 60/);
  assert.match(settingsErrors({ ...valid(), person_confidence: '' }).person_confidence, /number/);
  assert.match(settingsErrors({ ...valid(), min_sharpness: 'abc' }).min_sharpness, /number/);
});

test('cross-field rules: N <= M and min brightness < max brightness', () => {
  assert.ok(settingsErrors({ ...valid(), frames_to_confirm: '9' }).frames_to_confirm);
  assert.ok(settingsErrors({ ...valid(), min_brightness: '230' }).min_brightness);
});
