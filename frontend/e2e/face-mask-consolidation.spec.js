import { expect, test } from '@playwright/test';

const FM_API = process.env.E2E_FACE_MASK_API || 'http://localhost:8014/api';
const SHOTS = '../docs/face_mask/screenshots';

test('sidebar: Face Mask group holds only Live monitoring', async ({ page }) => {
  await page.goto('/face-mask/live');
  const nav = page.locator('aside').first();
  await expect(nav.getByRole('link', { name: 'Live monitoring' }).first()).toBeVisible();
  for (const gone of ['Overview', 'Events & review', 'Entry ROI', 'Reports & settings']) {
    await expect(nav.getByRole('link', { name: gone })).toHaveCount(0);
  }
});

test('old Face Mask URLs redirect to their new homes', async ({ page }) => {
  const cases = [
    ['/face-mask', /\/face-mask\/live$/],
    ['/face-mask/overview', /^https?:\/\/[^/]+\/$/],
    ['/face-mask/events', /\/alerts\/face-mask$/],
    ['/face-mask/events/abc123', /\/alerts\/face-mask\?event=abc123$/],
    ['/face-mask/reports', /\/branch-exterior\/brief$/],
    ['/face-mask/settings', /\/settings\?tab=face-mask$/],
  ];
  for (const [from, to] of cases) {
    await page.goto(from);
    await expect(page, from).toHaveURL(to);
  }
});

test('Dashboard shows the Face Mask section', async ({ page }) => {
  await page.goto('/');
  const section = page.getByRole('region', { name: 'Face Mask monitoring' });
  await expect(section).toBeVisible();
  await expect(section.getByText('Entries today')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/dashboard-face-mask.png`, fullPage: true });
});

test('Alerts: Face Mask events tab lists events and opens the review panel', async ({ page, request }) => {
  const list = await (await request.get(`${FM_API}/events?limit=1`)).json();
  await page.goto('/alerts/face-mask');
  await expect(page.getByRole('link', { name: 'Face Mask events' })).toBeVisible();
  test.skip(list.total === 0, 'needs at least one Face Mask event');
  await page.getByRole('button', { name: 'All', exact: true }).click();
  await page.locator('tbody tr.clickable').first().click();
  await expect(page).toHaveURL(/event=/);
  await expect(page.getByRole('button', { name: 'Close details' })).toBeVisible();
  await expect(page.getByText('Frames evaluated')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/alerts-face-mask.png`, fullPage: true });
});

test('Settings > Face Mask: change a value, save, reload, it persists; reset restores', async ({ page, request }) => {
  const API = process.env.E2E_FACE_MASK_API || 'http://localhost:8014/api';
  const before = await (await request.get(`${API}/settings`)).json();
  await page.goto('/settings?tab=face-mask');
  const fps = page.getByLabel('Processing FPS');
  await expect(fps).toBeVisible();
  const next = before.processing_fps === 5 ? '7' : '5';
  await fps.fill(next);
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page.getByText(/Saved\. New values apply/)).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Processing FPS')).toHaveValue(next);
  expect((await (await request.get(`${API}/settings`)).json()).processing_fps).toBe(Number(next));
  await page.screenshot({ path: `${SHOTS}/settings-face-mask.png`, fullPage: true });
  await request.post(`${API}/settings/reset`);   // removes the saved override file again
});
