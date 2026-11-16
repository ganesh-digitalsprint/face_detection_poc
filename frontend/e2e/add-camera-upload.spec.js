import { test, expect } from '@playwright/test';

test.use({ browserName: 'chromium', channel: 'chrome' });

test('Add camera keeps Upload between RTSP modes and fields, and preserves RTSP values', async ({ page }) => {
  await page.route('**/platform/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/platform', '');
    const bodies = {
      '/zones': [{ id: 'z', name: 'Test zone', city_count: 1, branch_count: 1 }],
      '/cities': [{ id: 'c', name: 'Test city', zone_id: 'z', branch_count: 1 }],
      '/branches': { items: [{ id: 'b', name: 'Test branch', code: 'TEST-01', camera_count: 0 }], total: 1 },
      '/branches/b': { id: 'b', name: 'Test branch', code: 'TEST-01' },
      '/branches/b/cameras': [],
      '/rtsp-templates': { hikvision: '/Streaming/Channels/{channel}0{stream}' },
      '/uploads': { items: [], total: 0 },
    };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(bodies[path] ?? {}) });
  });
  await page.goto('http://localhost:3000/branches/hierarchy/cameras/new?zone=z&city=c&branch=b&all=1');
  const dialog = page.getByRole('dialog', { name: 'Add camera' });
  const upload = dialog.getByRole('radio', { name: /^Upload Add recorded footage/ });
  await expect(upload).toBeVisible();
  const order = await upload.evaluate((element) => ({
    before: element.previousElementSibling?.textContent,
    after: element.parentElement?.nextElementSibling?.nextElementSibling?.textContent,
  }));
  expect(order.before).toContain('Auto-discover');
  expect(order.after).toContain('Recorder host / IP');
  await dialog.getByRole('textbox', { name: 'Recorder host / IP' }).fill('192.168.1.20');
  await upload.click();
  await expect(dialog.getByText('Drag and drop a video here')).toBeVisible();
  await expect(dialog.getByText('Test branch · TEST-01 (locked)')).toBeVisible();
  await expect(dialog.getByRole('combobox', { name: 'Assign to channel' })).toBeVisible();
  await expect(dialog.getByRole('combobox', { name: 'Use case' })).toBeVisible();
  await expect(dialog.getByRole('textbox', { name: 'Recorder host / IP' })).toHaveCount(0);
  await expect(dialog.getByRole('spinbutton', { name: 'RTSP port' })).toHaveCount(0);
  await expect(dialog.getByRole('combobox', { name: 'Stream' })).toHaveCount(0);
  await expect(dialog.getByRole('textbox', { name: 'Username' })).toHaveCount(0);
  await expect(dialog.getByRole('textbox', { name: /Password/ })).toHaveCount(0);
  await expect(dialog.locator('[aria-label="Masked RTSP URL preview"]')).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Upload video' })).toBeDisabled();
  await dialog.getByRole('radio', { name: /^NVR \/ recorder/ }).click();
  await expect(dialog.getByRole('textbox', { name: 'Recorder host / IP' })).toHaveValue('192.168.1.20');
});
