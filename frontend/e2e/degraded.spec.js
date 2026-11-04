import { expect, test } from '@playwright/test';

// Run against a stack whose Face Mask (and optionally Branch) URL points at a stopped port. See docs/face_mask/README.md.
const FM_DOWN = process.env.E2E_FM_DOWN === '1';
const BX_DOWN = process.env.E2E_BX_DOWN === '1';
const SHOTS = '../docs/face_mask/screenshots';

test.describe('Face Mask service stopped', () => {
  test.skip(!FM_DOWN, 'set E2E_FM_DOWN=1 against a stack with Face Mask stopped');

  test('Dashboard, Alerts, Brief and Settings degrade with the start command', async ({ page }) => {
    const start = /uv run uvicorn app\.main:app --reload --port 8014/;
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Face Mask · entrances today' })).toBeVisible();
    await expect(page.getByText(start).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/degraded-dashboard.png`, fullPage: true });
    await page.goto('/alerts/face-mask');
    await expect(page.getByText(start).first()).toBeVisible();
    await page.goto('/branch-exterior/brief');
    await expect(page.getByText(start).first()).toBeVisible();
    await expect(page.getByRole('search', { name: 'Security Brief filters' })).toBeVisible();
    await page.goto('/settings?tab=face-mask');
    await expect(page.getByText(start).first()).toBeVisible();
    await page.goto('/regions?use_case=branch_exterior');
    await expect(page.getByText('Network Error')).toHaveCount(0);
  });
});

test.describe('Branch Exterior service stopped', () => {
  test.skip(!BX_DOWN, 'set E2E_BX_DOWN=1 against a stack with Branch Exterior stopped');

  test('Face Mask pages keep working; the brief names Branch', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('region', { name: 'Face Mask monitoring' }).getByText('Entries today')).toBeVisible();
    await page.goto('/alerts/face-mask');
    await expect(page.getByText('Events', { exact: true }).first()).toBeVisible();
    await page.goto('/branch-exterior/brief');
    await expect(page.getByText(/Branch Exterior service unavailable/)).toBeVisible();
    await expect(page.getByLabel('Face Mask', { exact: true })).toBeVisible();
  });
});
