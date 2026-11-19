import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';

test('Face Mask layout mounts the local notification listener', async () => {
  const server = await createServer({ root: process.cwd(), server: { middlewareMode: true },
    appType: 'custom', logLevel: 'silent' });
  try {
    const { default: FmLayout } = await server.ssrLoadModule('/src/use-cases/face-mask/components/FmLayout.jsx');
    const html = renderToStaticMarkup(createElement(MemoryRouter, null, createElement(FmLayout)));
    assert.match(html, /aria-live="polite"/);
    assert.match(html, /Face Mask service/);
    const liveHtml = renderToStaticMarkup(createElement(MemoryRouter, { initialEntries: ['/face-mask/live'] }, createElement(FmLayout)));
    assert.doesNotMatch(liveHtml, /aria-live="polite"/);
    assert.match(liveHtml, /Face Mask service/);
  } finally {
    await server.close();
  }
});

test('newest Face Mask ticker event is marked Latest without changing its severity', async () => {
  const server = await createServer({ root: process.cwd(), server: { middlewareMode: true },
    appType: 'custom', logLevel: 'silent' });
  try {
    const { default: EventCard } = await server.ssrLoadModule('/src/use-cases/face-mask/components/FaceMaskConcealmentCard.jsx');
    const event = { id: 'new', camera_name: 'Entrance', first_seen: '2026-11-19T08:00:00Z',
      coverage_state: 'FULLY_COVERED', score: 0.9, status: 'OPEN', severity: 'HIGH', track_id: 3 };
    const latest = renderToStaticMarkup(createElement(EventCard, { event, latest: true, onSelect: () => {} }));
    const older = renderToStaticMarkup(createElement(EventCard, { event, onSelect: () => {} }));
    assert.match(latest, /Latest/);
    assert.match(latest, /HIGH/);
    assert.doesNotMatch(older, /Latest/);
  } finally { await server.close(); }
});
