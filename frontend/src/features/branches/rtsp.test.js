import test from 'node:test';
import assert from 'node:assert/strict';
import { maskedPreview, parseRtspUrl } from './rtsp.js';

test('parses RTSP fields and masks the secret in preview', () => {
  const fields = parseRtspUrl('rtsp://admin:secret@192.168.1.5:554/live');
  assert.equal(fields.password, 'secret');
  const preview = maskedPreview({ ...fields, template_key: 'generic' });
  assert.ok(preview.includes('••••••••'));
  assert.ok(!preview.includes('secret'));
});

test('rejects non-RTSP URL schemes', () => {
  assert.throws(() => parseRtspUrl('file:///etc/passwd'));
  assert.throws(() => parseRtspUrl('http://127.0.0.1/live'));
});

test('retains secure RTSP scheme and query without exposing the password', () => {
  const fields = parseRtspUrl('rtsps://admin:secret@10.0.0.8:8554/live?profile=main');
  const preview = maskedPreview({ ...fields, template_key: 'generic' });
  assert.equal(fields.scheme, 'rtsps');
  assert.ok(preview.startsWith('rtsps://'));
  assert.ok(preview.endsWith('/live?profile=main'));
  assert.ok(!preview.includes('secret'));
});
