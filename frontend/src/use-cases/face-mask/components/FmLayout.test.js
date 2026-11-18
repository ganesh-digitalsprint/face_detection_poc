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
  } finally {
    await server.close();
  }
});
