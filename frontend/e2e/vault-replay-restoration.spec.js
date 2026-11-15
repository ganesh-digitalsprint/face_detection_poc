import { expect, test } from '@playwright/test';

test.use({ channel: 'chrome' });
const contextKey = 'vault-room-replay:v1';
const initial = { version: 1, sessionId: 'old-replay', sourceId: 'old-source', profileId: 'upload' };
const event = (id, session, sourceId, seconds) => ({ id, session_id: session, source_id: sourceId,
  type: 'VAULT_DOOR_INTERACTION', source: 'upload', replay: true, test_mode: true,
  camera_id: sourceId, track_ids: [1], zone_id: 'vault_door_roi', description: id,
  video_timestamp_seconds: seconds, created_at: `2026-11-13T00:00:0${seconds}Z`, evidence_reference: id });
const oldEvents = [event('old-first', 'old-replay', 'old-source', 1), event('old-second', 'old-replay', 'old-source', 2)];
const newEvents = [event('new-first', 'new-replay', 'new-replay', 1)];
const snapshot = (id, status, time = 4) => ({ session_id: id, source_id: id === 'old-replay' ? 'old-source' : id,
  status, current_time: time, metadata: { duration: 25, fps: 24, width: 1280, height: 720, size_bytes: 20 },
  state: { required_persons: 2, door: 'LOCKED' }, events: [], alerts: [], frame_sequence: 0,
  processed_frames: 20, progress: time / 25, finalized: status === 'completed' });
const rows = (page) => page.locator('.vault-activity-events > .activity-timeline .activity-event-row');

async function harness(page, { missing = false, status = 'completed' } = {}) {
  const state = { missing, status, time: 4, uploads: 0, starts: 0, deletes: 0, failStart: false, failUpload: false,
    failHistory: false, delayHistory: false, pending: null, activityQueries: [] };
  await page.addInitScript(({ contextKey, initial }) => {
    if (!localStorage.getItem(contextKey)) {
      localStorage.setItem(contextKey, JSON.stringify(initial));
      localStorage.setItem('vault-room-ui:v1', JSON.stringify({ view: 'room', source: 'upload', scope: 'events' }));
    }
  }, { contextKey, initial });
  await page.route('**/api/v1/vault-room/**', async (route) => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    if (path.endsWith('/events')) return route.continue();
    if (path.endsWith('/video-sessions') && request.method() === 'POST') {
      state.uploads++; return route.fulfill(state.failUpload ? { status: 500, json: { detail: 'upload failed' } }
        : { status: 201, json: snapshot('new-replay', 'uploaded') });
    }
    if (path.endsWith('/new-replay/start')) {
      state.starts++;
      return route.fulfill(state.failStart ? { status: 500, json: { detail: 'start failed' } }
        : { json: snapshot('new-replay', 'completed') });
    }
    if (path.includes('/video-sessions/')) {
      if (request.method() === 'DELETE') { state.deletes++; return route.fulfill({ json: {} }); }
      if (path.endsWith('/old-replay')) return route.fulfill(state.missing ? { status: 404, json: { detail: 'Replay not found' } }
        : { json: snapshot('old-replay', state.status, state.time) });
      if (path.endsWith('/new-replay')) return route.fulfill({ json: snapshot('new-replay', 'completed') });
    }
    if (path.endsWith('/activity-events')) {
      state.activityQueries.push(url.search);
      expect(url.searchParams.get('order')).toBe('asc');
      const old = path.includes('/old-replay/');
      expect(url.searchParams.get('source_id')).toBe(old ? 'old-source' : 'new-replay');
      if (old && state.delayHistory) {
        state.delayHistory = false;
        await new Promise((resolve) => { state.pending = resolve; });
      }
      try { return await route.fulfill(old && state.failHistory ? { status: 500, json: { detail: 'temporary activity failure' } }
        : { json: { items: old ? oldEvents : newEvents, total: old ? 2 : 1 } }); }
      catch { return; } // The obsolete request may have been aborted during context replacement.
    }
    if (path.includes('/activity-events/')) {
      if (path.endsWith('/evidence')) return route.fulfill({ contentType: 'image/png',
        body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV1EAAAAASUVORK5CYII=', 'base64') });
      const id = path.split('/').at(-1);
      return route.fulfill({ json: [...oldEvents, ...newEvents].find((e) => e.id === id) });
    }
    return route.continue();
  });
  return state;
}
async function assertOld(page) {
  await expect(rows(page)).toHaveCount(2);
  await expect(rows(page).nth(0)).toContainText('old-first');
  await expect(rows(page).nth(1)).toContainText('old-second');
}
async function choose(page) {
  await page.getByLabel('Choose replay video').setInputFiles({ name: 'next.webm', mimeType: 'video/webm', buffer: Buffer.from('test upload') });
}

test('Vault Monitoring submenus preserve replay, query parameters, refresh selection and browser history', async ({ page }) => {
  const state = await harness(page, { missing: true });
  await page.goto('/vault-access?view=room&source=upload&camera=42'); await assertOld(page);
  const nav = page.getByRole('navigation', { name: 'Main', exact: true }).first();
  const group = nav.getByRole('button', { name: 'Vault Monitoring', exact: true });
  await expect(group).toHaveAttribute('aria-expanded', 'true');
  await expect(nav.getByRole('link', { name: 'Vault Room Camera', exact: true })).toHaveAttribute('aria-current', 'page');
  const previousUrl = page.url();
  await group.click(); await expect(group).toHaveAttribute('aria-expanded', 'false');
  expect(page.url()).toBe(previousUrl);
  await group.click();
  await nav.getByRole('link', { name: 'Zones & Regions', exact: true }).click();
  expect(new URL(page.url()).searchParams.get('source')).toBe('upload');
  expect(new URL(page.url()).searchParams.get('camera')).toBe('42');
  await page.reload();
  await expect(nav.getByRole('link', { name: 'Zones & Regions', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(group).toHaveAttribute('aria-expanded', 'true');
  await nav.getByRole('link', { name: 'Entrance Camera', exact: true }).click();
  await page.reload();
  await expect(nav.getByRole('link', { name: 'Entrance Camera', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.goBack();
  await expect(nav.getByRole('link', { name: 'Zones & Regions', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.goBack(); await assertOld(page);
  await expect(nav.getByRole('link', { name: 'Vault Room Camera', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.goForward();
  await expect(nav.getByRole('link', { name: 'Zones & Regions', exact: true })).toHaveAttribute('aria-current', 'page');
  await page.goto('/vault-access');
  await expect(nav.getByRole('link', { name: 'Zones & Regions', exact: true })).toHaveAttribute('aria-current', 'page');
  expect(JSON.parse(await page.evaluate((key) => localStorage.getItem(key), contextKey))).toEqual(initial);
  expect(state.uploads).toBe(0); expect(state.starts).toBe(0); expect(state.deletes).toBe(0);
});

test('completed worker refresh restores view, source, Events, history and evidence; navigation never deletes it', async ({ page }) => {
  const state = await harness(page);
  await page.goto('/vault-access'); await assertOld(page);
  await expect(page.getByRole('button', { name: 'Vault Room Camera', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Upload video', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.reload(); await assertOld(page);
  await rows(page).first().click();
  await expect(page.getByAltText('Evidence for VAULT_DOOR_INTERACTION')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Zones & Regions', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Zones & Regions', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Vault Room Camera', exact: true }).click(); await assertOld(page);
  await page.getByRole('link', { name: 'Dashboard', exact: true }).first().click();
  await page.goto('/vault-access'); await assertOld(page);
  expect(state.uploads).toBe(0); expect(state.starts).toBe(0); expect(state.deletes).toBe(0);
});

test('worker 404 retains durable history; transient event errors and choosing a file retain rows', async ({ page }) => {
  const state = await harness(page, { missing: true });
  await page.goto('/vault-access'); await assertOld(page);
  await expect(page.getByText('The replay worker is no longer available. Saved activity events and evidence remain available.')).toBeVisible();
  state.failHistory = true;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Retry events' })).toBeVisible(); await assertOld(page);
  state.failHistory = false;
  await page.getByRole('button', { name: 'Retry events' }).click(); await assertOld(page);
  await choose(page); await assertOld(page);
  expect(JSON.parse(await page.evaluate((key) => localStorage.getItem(key), contextKey)).sessionId).toBe('old-replay');
  await page.reload(); await assertOld(page);
  expect(state.starts).toBe(0); expect(state.deletes).toBe(0);
});

test('in-progress refresh reconnects to the same worker and latest source time without upload or start', async ({ page }) => {
  const state = await harness(page, { status: 'processing' });
  await page.goto('/vault-access'); await assertOld(page);
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible();
  state.time = 9;
  await page.reload(); await assertOld(page);
  await expect(page.getByText('9.0s / 25.0s')).toBeVisible();
  expect(state.uploads).toBe(0); expect(state.starts).toBe(0); expect(state.deletes).toBe(0);
});

test('upload failure never replaces persisted replay identifiers or clears previous events', async ({ page }) => {
  const state = await harness(page, { missing: true });
  await page.goto('/vault-access'); await assertOld(page); await choose(page);
  state.failUpload = true;
  await page.getByRole('button', { name: 'Process video', exact: true }).click();
  await expect.poll(() => state.uploads).toBe(1);
  await expect(page.getByRole('button', { name: 'Process video', exact: true })).toBeEnabled();
  await assertOld(page);
  expect(JSON.parse(await page.evaluate((key) => localStorage.getItem(key), contextKey))).toEqual(initial);
  await page.reload(); await assertOld(page);
  expect(state.starts).toBe(0); expect(state.deletes).toBe(0);
});

test('failed start keeps old context; successful start alone replaces it and late old requests cannot overwrite it', async ({ page }) => {
  const state = await harness(page, { missing: true });
  await page.goto('/vault-access'); await assertOld(page); await choose(page);
  state.failStart = true;
  await page.getByRole('button', { name: 'Process video', exact: true }).click();
  await expect.poll(() => state.starts).toBe(1); await assertOld(page);
  expect(JSON.parse(await page.evaluate((key) => localStorage.getItem(key), contextKey)).sessionId).toBe('old-replay');
  state.failStart = false; state.delayHistory = true;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect.poll(() => Boolean(state.pending)).toBe(true);
  await page.getByRole('button', { name: 'Process video', exact: true }).click();
  await expect(rows(page)).toHaveCount(1); await expect(rows(page).first()).toContainText('new-first');
  state.pending(); await expect(rows(page)).toHaveCount(1);
  expect(JSON.parse(await page.evaluate((key) => localStorage.getItem(key), contextKey)).sessionId).toBe('new-replay');
  await page.reload(); await expect(rows(page)).toHaveCount(1); await expect(rows(page).first()).toContainText('new-first');
  expect(state.uploads).toBe(1); expect(state.starts).toBe(2);
});
