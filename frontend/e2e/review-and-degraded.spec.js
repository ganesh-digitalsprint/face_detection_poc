import { expect, test } from '@playwright/test';

const FM_API = process.env.E2E_FACE_MASK_API || 'http://localhost:8014/api';
const SHOTS = '../docs/face_mask/screenshots';

test('review workflow in the Alerts detail panel: under review -> false positive -> close with remarks', async ({ page, request }) => {
  const open = await (await request.get(`${FM_API}/events?statuses=OPEN&limit=1`)).json();
  test.skip(open.total === 0, 'needs one OPEN Face Mask event');
  const id = open.items[0].id;
  await page.goto(`/alerts/face-mask?event=${id}`);
  const panel = page.getByRole('complementary', { name: /Concealment event/ });
  await expect(panel).toBeVisible();
  await expect(panel.locator('img').first()).toBeVisible();
  await panel.getByLabel('Your name (for the audit trail)').fill('e2e-reviewer');

  await panel.getByRole('button', { name: 'Mark under review' }).click();
  await expect(panel.getByRole('button', { name: 'False positive' })).toBeVisible();

  await panel.getByRole('button', { name: 'False positive' }).click();
  await expect(panel.getByRole('button', { name: 'False positive' })).toBeDisabled();   // reason required first
  await panel.getByLabel(/Reason/).fill('Cap only, face fully visible');
  await panel.getByRole('button', { name: 'False positive' }).click();
  await expect(panel.getByRole('button', { name: 'Close', exact: true })).toBeVisible();

  await panel.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'Close', exact: true })).toBeDisabled();
  await panel.getByLabel(/Closing remarks/).fill('Reviewed in e2e run');
  await panel.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(panel.getByText('This event is closed.')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/alerts-face-mask-reviewed.png`, fullPage: true });

  const final = await (await request.get(`${FM_API}/events/${id}`)).json();
  expect(final.status).toBe('CLOSED');
  expect(final.remarks).toBe('Reviewed in e2e run');
  const trail = await (await request.get(`${FM_API}/events/${id}/actions`)).json();
  expect(trail.map((a) => a.to_status)).toEqual(['UNDER_REVIEW', 'FALSE_POSITIVE', 'CLOSED']);
});
