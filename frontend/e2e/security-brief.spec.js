import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const SHOTS = '../docs/face_mask/screenshots';

test('filters sit on one line at 1366px and Period offers All time', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 800 });
  await page.goto('/branch-exterior/brief');
  const bar = page.getByRole('search', { name: 'Security Brief filters' });
  await expect(bar).toBeVisible();
  const tops = await bar.locator('label').evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
  expect(tops).toHaveLength(7);
  expect(Math.max(...tops) - Math.min(...tops), `label tops ${tops}`).toBeLessThanOrEqual(2);
  const options = await bar.getByLabel('Period').locator('option').allTextContents();
  expect(options).toEqual(['Last 24 hours', 'Last 7 days', 'Last 30 days', 'All time', 'Custom']);
  await expect(bar.getByLabel('From')).toBeDisabled();
  await bar.getByLabel('Period').selectOption('custom');
  await expect(bar.getByLabel('From')).toBeEnabled();
  await page.screenshot({ path: `${SHOTS}/brief-filters.png`, fullPage: true });
});

test('CSV download for All use cases is one combined file; unreachable ones are named', async ({ page }) => {
  await page.goto('/branch-exterior/brief');
  await page.getByLabel('Download format').selectOption('csv');
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download' }).click()]);
  expect(download.suggestedFilename()).toMatch(/^all_use_cases_events_\d{4}-\d{2}-\d{2}\.csv$/);
  const text = readFileSync(await download.path(), 'utf8');
  expect(text).toMatch(/use_case,event_id,timestamp_utc,camera,zone_or_roi,track_id,type,score,severity,status,reviewer,remarks,message/);
  expect(text).toMatch(/# Skipped Vault Access/);
  await expect(page.getByText('Skipped Vault Access')).toBeVisible();
});

test('Face Mask only: status filter changes the numbers to match the API', async ({ page, request }) => {
  const API = process.env.E2E_FACE_MASK_API || 'http://localhost:8014/api';
  const total = async (q) => (await (await request.get(`${API}/events?limit=1${q}`)).json()).total;
  await page.goto('/branch-exterior/brief');
  const bar = page.getByRole('search', { name: 'Security Brief filters' });
  await bar.getByLabel('Use case').selectOption('face_mask');
  await bar.getByLabel('Period').selectOption('all');
  const section = page.getByLabel('Face Mask', { exact: true });
  await expect(section).toBeVisible();
  await expect(page.getByText('Summary -')).toHaveCount(0);
  const tile = (name) => section.locator('.bx-kpis > div', { hasText: name }).locator('.v');
  await expect(tile('Concealed events')).toHaveText(String(await total('')));
  await bar.getByLabel('Status').selectOption('closed');
  await expect(tile('Concealed events')).toHaveText(String(await total('&status=CLOSED')));
  await bar.getByLabel('Use case').selectOption('branch_exterior');
  await expect(bar.getByLabel('Covering')).toBeDisabled();
});

test('print view shows the applied filters', async ({ page }) => {
  await page.goto('/branch-exterior/brief');
  await page.getByRole('search').getByLabel('Use case').selectOption('face_mask');
  await page.emulateMedia({ media: 'print' });
  await expect(page.getByText(/Security Brief · Use case: Face Mask/)).toBeVisible();
  await expect(page.getByRole('search')).toBeHidden();
});
