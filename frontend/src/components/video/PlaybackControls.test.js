import assert from 'node:assert/strict';
import test from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

test('Stop button is neutral when idle, primary when running, and disabled when stopping', async () => {
  const vite = await createServer({ root: process.cwd(), server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
  try {
    const { StopButton, PlaybackBadge, PlaybackProgress } = await vite.ssrLoadModule('/src/components/video/PlaybackControls.jsx');
    const render = (component, props) => renderToStaticMarkup(createElement(component, props));
    const idle = render(StopButton, { status: 'STOPPED', running: false });
    assert.match(idle, /disabled=""/);
    assert.doesNotMatch(idle, /bx-btn-primary/);
    const running = render(StopButton, { status: 'PROCESSING', running: true });
    assert.match(running, /bx-btn-primary/);
    assert.doesNotMatch(running, /disabled=""/);
    const stopping = render(StopButton, { status: 'STOPPING', running: true });
    assert.match(stopping, /Stopping/);
    assert.match(stopping, /disabled=""/);
    assert.match(render(PlaybackBadge, { status: 'DONE', running: false }), /FINISHED/);
    assert.match(render(PlaybackProgress, { status: { frames_read: 42, frames_total: 134, native_fps: 1 } }), /00:42 \/ 02:14/);
  } finally {
    await vite.close();
  }
});
