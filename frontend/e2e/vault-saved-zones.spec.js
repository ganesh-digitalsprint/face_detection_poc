import { expect, test } from '@playwright/test';

test.use({ channel: 'chrome' });
const keys = ['person_monitoring_roi', 'vault_area_roi', 'vault_door_roi', 'vault_door_handle_roi', 'ornament_area_roi', 'tray_area_roi'];
const initialZones = keys.map((id, index) => ({ id, name: `Region ${index + 1}`, reference: 'bottom_center', enabled: true,
  confirmation_seconds: 1, polygon: [[.1, .1], [.6 + index * .01, .1], [.6, .8], [.1, .8]] }));
const panel = (page) => page.getByRole('region', { name: 'Load saved zones', exact: true });
const cards = (page) => page.locator('.zone-region-card');

async function setup(page, { active = false } = {}) {
  const state = { profiles: { upload: { id: 'upload', name: 'Default upload', version: 1, zones: structuredClone(initialZones) },
    alternate: { id: 'alternate', name: 'Night shift', version: 2, zones: [{ ...structuredClone(initialZones[4]), name: 'Ornament station' }] } },
    puts: [], workerMutations: [], failList: false, failDetails: false, empty: false, delay: false, release: null };
  await page.addInitScript((active) => {
    localStorage.setItem('vault-room-ui:v1', JSON.stringify({ view: 'zones', source: 'upload', scope: 'events' }));
    if (active) localStorage.setItem('vault-room-replay:v1', JSON.stringify({ version: 1, sessionId: 'active-replay', sourceId: 'active-replay', profileId: 'upload' }));
  }, active);
  await page.route('**/api/v1/vault-room/**', async (route) => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path.includes('/region-profiles')) {
      const id = path.split('/').at(-1);
      if (id === 'region-profiles') return route.fulfill(state.failList ? { status: 500, json: { detail: 'Profiles temporarily unavailable' } }
        : { json: state.empty ? [] : Object.values(state.profiles).map(({ zones, ...profile }) => profile) });
      if (request.method() === 'PUT') {
        const value = request.postDataJSON(); state.puts.push({ id, ...value });
        state.profiles[id] = { ...state.profiles[id], ...value, version: value.version + 1 };
        return route.fulfill({ json: state.profiles[id] });
      }
      if (id === 'alternate' && state.delay) { state.delay = false; await new Promise((resolve) => { state.release = resolve; }); }
      if (id === 'alternate' && state.failDetails) return route.fulfill({ status: 500, json: { detail: 'Selected configuration unavailable' } });
      return route.fulfill({ json: state.profiles[id] || { id, name: id, version: 0, zones: [] } });
    }
    if (path.includes('/video-sessions')) {
      if (request.method() !== 'GET') state.workerMutations.push(path);
      return route.fulfill({ json: { session_id: 'active-replay', status: 'processing', current_time: 4,
        state: { required_persons: 2 }, alerts: [], events: [], progress: .2, frame_sequence: 0, finalized: false,
        metadata: { duration: 25, width: 1280, height: 720, fps: 24 } } });
    }
    if (path.endsWith('/activity-events')) return route.fulfill({ json: { total: 1, items: [{ id: 'durable-event',
      session_id: 'active-replay', source_id: 'active-replay', source: 'upload', replay: true, test_mode: true,
      type: 'VAULT_DOOR_INTERACTION', track_ids: [1], video_timestamp_seconds: 2, created_at: '2026-11-13T00:00:02Z' }] } });
    return route.continue();
  });
  await page.goto('/vault-access?view=zones&source=upload'); await expect(cards(page)).toHaveCount(6);
  return state;
}
async function frame(page) {
  // An intrinsic 1280x720 media fixture exercises the existing SVG scaling, with no inference/upload.
  await page.evaluate(() => new Promise((resolve) => {
    const image = new Image(); image.onload = resolve;
    image.src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"/>');
    document.querySelector('.room-camera-frame').appendChild(image);
  }));
  await expect(page.getByLabel('Zones on the frame')).toBeVisible();
}
async function open(page) {
  await page.getByRole('button', { name: 'Load Zones', exact: true }).click();
  await expect(panel(page)).toBeVisible();
}

test('load restores all polygon types/scaling, confirms unsaved edits, saves the selected profile and survives refresh', async ({ page }) => {
  const state = await setup(page); await frame(page); await open(page);
  await expect(panel(page).getByText('6 regions', { exact: true })).toBeVisible();
  const svg = page.getByLabel('Zones on the frame');
  await expect(svg).toHaveAttribute('viewBox', '0 0 1280 720');
  await expect(svg.locator('polygon').first()).toHaveAttribute('points', '128,72 768,72 768,576 128,576');
  await panel(page).getByLabel('Saved zone configuration').selectOption('alternate');
  await expect(panel(page).getByText('1 regions', { exact: true })).toBeVisible();
  await page.getByLabel('Zone set name', { exact: true }).fill('Unsaved draft');
  page.once('dialog', (dialog) => dialog.dismiss());
  await panel(page).getByRole('button', { name: 'Load zones', exact: true }).click();
  await expect(cards(page)).toHaveCount(6);
  await expect(page.getByLabel('Zone set name', { exact: true })).toHaveValue('Unsaved draft');
  page.once('dialog', (dialog) => dialog.accept());
  await panel(page).getByRole('button', { name: 'Load zones', exact: true }).click();
  await expect(cards(page)).toHaveCount(1); await expect(cards(page).first()).toContainText('Ornament station');
  expect(state.puts).toHaveLength(0);
  await expect(svg.locator('polygon')).toHaveCount(1);
  await page.setViewportSize({ width: 768, height: 900 });
  await expect(svg.locator('polygon').first()).toHaveAttribute('points', '128,72 819.2,72 768,576 128,576');
  await page.getByRole('button', { name: 'Edit Ornament station', exact: true }).click();
  await page.getByLabel('Ornament station reference point').selectOption('center');
  await page.getByRole('button', { name: 'Finish editing', exact: true }).click();
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect.poll(() => state.puts.length).toBe(1);
  expect(state.puts[0].id).toBe('alternate');
  expect(state.puts[0].zones[0].polygon).toEqual(initialZones[4].polygon);
  expect(state.puts[0].zones[0].reference).toBe('center');
  expect(state.profiles.upload.zones).toEqual(initialZones);
  await page.reload(); await expect(cards(page)).toHaveCount(1); await open(page);
  await expect(panel(page).getByRole('button', { name: 'Zones in use' })).toBeDisabled();
  await panel(page).getByLabel('Saved zone configuration').selectOption('upload');
  await panel(page).getByRole('button', { name: 'Load zones', exact: true }).click();
  await expect(cards(page)).toHaveCount(6);
});

test('list/detail failures and edits during a pending load do not discard current zones', async ({ page }) => {
  const state = await setup(page); state.failList = true; await open(page);
  await expect(panel(page).getByRole('alert')).toContainText('Profiles temporarily unavailable');
  await expect(cards(page)).toHaveCount(6);
  state.failList = false; await panel(page).getByRole('button', { name: 'Retry' }).click();
  await panel(page).getByLabel('Saved zone configuration').selectOption('alternate');
  await expect(panel(page).getByText('1 regions', { exact: true })).toBeVisible();
  state.failDetails = true;
  await panel(page).getByRole('button', { name: 'Load zones', exact: true }).click();
  await expect(panel(page).getByRole('alert')).toContainText('Selected configuration unavailable');
  await expect(cards(page)).toHaveCount(6);
  state.failDetails = false; state.delay = true;
  await panel(page).getByRole('button', { name: 'Retry' }).click();
  await expect.poll(() => Boolean(state.release)).toBe(true);
  await page.getByLabel('Zone set name', { exact: true }).fill('New edit during request'); state.release();
  await expect(panel(page).getByRole('alert')).toContainText('regions changed while loading');
  await expect(cards(page)).toHaveCount(6);
  await expect(page.getByLabel('Zone set name', { exact: true })).toHaveValue('New edit during request');
  expect(state.puts).toHaveLength(0);
});

test('empty state is explicit; loading a profile does not mutate an active replay or its event context', async ({ page }) => {
  const state = await setup(page, { active: true }); await open(page);
  await panel(page).getByLabel('Saved zone configuration').selectOption('alternate');
  await panel(page).getByRole('button', { name: 'Load zones', exact: true }).click(); await expect(cards(page)).toHaveCount(1);
  expect(state.workerMutations).toHaveLength(0);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('vault-room-replay:v1')).sessionId)).toBe('active-replay');
  await page.getByRole('button', { name: 'Vault Room Camera', exact: true }).click();
  await expect(page.locator('.activity-event-row')).toHaveCount(1);
  await page.getByRole('button', { name: 'Zones & Regions', exact: true }).click();
  state.empty = true;
  await page.getByRole('button', { name: 'Load Zones', exact: true }).click();
  await page.getByRole('button', { name: 'Load Zones', exact: true }).click();
  await expect(panel(page).getByText(/No saved zone configurations yet/)).toBeVisible();
  await expect(cards(page)).toHaveCount(1); expect(state.puts).toHaveLength(0);
});
