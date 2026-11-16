import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('an open phone replay alert remains in Active for operator review', async () => {
  const server = await createServer({ root: process.cwd(), server: { middlewareMode: true },
    appType: 'custom', logLevel: 'silent' });
  try {
    const module = await server.ssrLoadModule('/src/use-cases/vault-monitoring/components/vault/VaultRoomReplayAlerts.jsx');
    const alert = { id: 'phone-1', session_id: 'replay-1', type: 'MOBILE_PHONE_DETECTED', title: 'Mobile Phone Detected',
      severity: 'HIGH', status: 'OPEN', message: '[REPLAY TEST] Mobile phone detected (82% confidence).',
      evidence_url: '/api/v1/vault-room/video-sessions/replay-1/evidence/phone-1' };
    assert.equal(module.visibleReplayAlertScope('active', [alert]), 'active');
    const html = renderToStaticMarkup(createElement(module.default, {
      replay: { session_id: 'replay-1', alerts: [alert, { ...alert, id: 'old-phone', session_id: 'replay-old',
        message: 'Old video must not appear' }] },
    }));
    assert.match(html, /Mobile phone detected/);
    assert.match(html, /82% confidence/);
    assert.match(html, /Active \(1\)/);
    assert.match(html, /aria-selected="true"[^>]*>Active/);
    assert.match(html, /Replay test/);
    assert.doesNotMatch(html, /Old video must not appear/);
  } finally {
    await server.close();
  }
});
