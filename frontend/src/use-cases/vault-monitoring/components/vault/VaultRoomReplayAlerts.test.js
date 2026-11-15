import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('a short-lived resolved phone replay alert remains immediately visible', async () => {
  const server = await createServer({ root: process.cwd(), server: { middlewareMode: true },
    appType: 'custom', logLevel: 'silent' });
  try {
    const module = await server.ssrLoadModule('/src/use-cases/vault-monitoring/components/vault/VaultRoomReplayAlerts.jsx');
    const alert = { id: 'phone-1', type: 'MOBILE_PHONE_DETECTED', title: 'Mobile Phone Detected',
      severity: 'HIGH', status: 'RESOLVED', message: '[REPLAY TEST] Mobile phone detected (82% confidence).',
      evidence_url: '/api/v1/vault-room/video-sessions/replay-1/evidence/phone-1' };
    assert.equal(module.visibleReplayAlertScope('active', [alert]), 'history');
    const html = renderToStaticMarkup(createElement(module.default, {
      replay: { session_id: 'replay-1', alerts: [alert] },
    }));
    assert.match(html, /Mobile phone detected/);
    assert.match(html, /82% confidence/);
    assert.match(html, /History \(1\)/);
    assert.match(html, /aria-selected="true"[^>]*>History/);
    assert.match(html, /Replay test/);
  } finally {
    await server.close();
  }
});
