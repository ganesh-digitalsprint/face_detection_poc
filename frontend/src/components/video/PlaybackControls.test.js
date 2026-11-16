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

test('shared Start/Stop controls follow the playback state matrix', async () => {
  const vite = await createServer({ root: process.cwd(), server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
  try {
    const { StartStopControls } = await vite.ssrLoadModule('/src/components/video/PlaybackControls.jsx');
    const render = (props) => renderToStaticMarkup(createElement(StartStopControls, { onStart() {}, onStop() {}, ...props }));
    const buttons = (html) => [...html.matchAll(/<button[^>]*>[^<]*<\/button>/g)].map(([button]) => button);
    for (const props of [{ selected: false, status: 'STOPPED' }, { selected: true, status: 'STARTING', starting: true },
      { selected: true, status: 'STOPPING', stopping: true }]) {
      const [start, stop] = buttons(render(props));
      assert.match(start, /disabled=""/); assert.match(stop, /disabled=""/);
      assert.doesNotMatch(start, /bx-btn-primary/); assert.doesNotMatch(stop, /bx-btn-primary/);
    }
    const [runningStart, runningStop] = buttons(render({ selected: true, status: 'PROCESSING', running: true }));
    assert.match(runningStart, /disabled=""/); assert.match(runningStop, /bx-btn-primary/);
    const [pausedStart, pausedStop] = buttons(render({ selected: true, status: 'STOPPED', canResume: true, positionSeconds: 12 }));
    assert.match(pausedStart, /bx-btn-primary/); assert.match(pausedStart, /Continue from 00:12/);
    assert.match(pausedStop, /disabled=""/);
    for (const status of ['FINISHED', 'ERROR']) {
      const [start, stop] = buttons(render({ selected: true, status }));
      assert.match(start, /bx-btn-primary/); assert.match(stop, /disabled=""/);
    }
    const [cameraStart, cameraStop] = buttons(render({ selected: true, status: 'STOPPED', canRestartCamera: true }));
    assert.match(cameraStart, /bx-btn-primary/);
    assert.match(cameraStop, /disabled=""/);
  } finally { await vite.close(); }
});
