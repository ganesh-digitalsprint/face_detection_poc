import { expect, test } from '@playwright/test';

const FM_API = process.env.E2E_FACE_MASK_API || 'http://localhost:8014/api';
const SHOTS = '../docs/face_mask/screenshots';

test('Regions & Zones loads with no network error and lists zones from both services', async ({ page }) => {
  await page.goto('/regions');
  await expect(page.getByRole('group', { name: 'Use case' })).toBeVisible();
  await expect(page.getByText('Network Error')).toHaveCount(0);
  await expect(page.getByText('Cannot reach')).toHaveCount(0);
  await expect(page.getByRole('columnheader', { name: 'Use case' })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/regions-all.png`, fullPage: true });
});

test('Branch Exterior zones editor still renders under the common page', async ({ page }) => {
  await page.goto('/regions?use_case=branch_exterior');
  await expect(page.getByRole('button', { name: '+ Draw new zone' })).toBeVisible();
  await expect(page.getByText('Network Error')).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/regions-branch.png`, fullPage: true });
});

test('Face Mask: draw an Entry ROI with an inward arrow, save, reload, it persists', async ({ page, request }) => {
  const cameras = await (await request.get(`${FM_API}/cameras`)).json();
  test.skip(cameras.length === 0, 'needs at least one Face Mask camera or analysed video');
  const camera = cameras[0];
  const name = `E2E Gate ${Date.now()}`;

  await page.goto(`/regions?use_case=face_mask&camera=${camera.id}`);
  const canvas = page.getByLabel('Draw the entry region on the camera view');
  await expect(canvas).toBeVisible();
  await page.getByRole('button', { name: '+ Draw a new entry' }).click();

  const box = await canvas.boundingBox();
  const at = (fx, fy) => ({ x: box.x + box.width * fx, y: box.y + box.height * fy });
  for (const [fx, fy] of [[0.15, 0.45], [0.85, 0.45], [0.85, 0.9], [0.15, 0.9]]) await page.mouse.click(at(fx, fy).x, at(fx, fy).y);
  await page.getByRole('button', { name: 'Close the area' }).click();
  await page.getByRole('button', { name: 'Next: draw the inward arrow' }).click();
  await page.mouse.click(at(0.5, 0.8).x, at(0.5, 0.8).y);
  await page.mouse.click(at(0.5, 0.55).x, at(0.5, 0.55).y);
  await page.getByPlaceholder('e.g. Grill Gate').fill(name);
  await page.screenshot({ path: `${SHOTS}/regions-face-mask-draw.png`, fullPage: true });
  await page.getByRole('button', { name: 'Save entry area' }).click();
  await expect(page.getByText(`Saved "${name}"`)).toBeVisible();

  await page.reload();
  await expect(page.getByText(name)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/regions-face-mask-saved.png`, fullPage: true });

  const saved = (await (await request.get(`${FM_API}/roi?camera_id=${camera.id}`)).json()).find((r) => r.name === name);
  expect(saved).toBeTruthy();
  expect(saved).toMatchObject({ use_case: 'face_mask', zone_type: 'entry_roi', enabled: true });
  expect(saved.inward_vector.y).toBeLessThan(0); // arrow drawn upwards = people enter walking up the frame

  await request.delete(`${FM_API}/roi/${saved.id}`); // leave the real data as found
});

test('old /face-mask/roi URL redirects to Regions with Face Mask selected', async ({ page }) => {
  await page.goto('/face-mask/roi?camera=abc');
  await expect(page).toHaveURL(/\/regions\?use_case=face_mask&camera=abc/);
});
