import { test, expect } from '@playwright/test';

test('Alert Center filters expose usable options, apply selections and keep the date panel dismissible', async ({ page }) => {
  await page.route('**/alert-service/api/v1/alerts**', async (route) => {
    const summary = new URL(route.request().url()).pathname.endsWith('/summary');
    await route.fulfill({ status:200, contentType:'application/json', body:JSON.stringify(summary
      ? { total:0, by_status:{ OPEN:0, ACKNOWLEDGED:0, RESOLVED:0, DISMISSED:0 }, by_severity:{ INFO:0, WARNING:0, HIGH:0, CRITICAL:0 } }
      : { items:[], next_cursor:null, has_more:false }) });
  });
  await page.route('**/platform/branches/search**', (route) => route.fulfill({ status:200, contentType:'application/json', body:JSON.stringify([
    { id:'branch-1', code:'C001', name:'Central Branch' },
    { id:'branch-2', code:'C002', name:'A Branch With A Long Display Name' },
  ]) }));
  await page.route('**/platform/branches/*/cameras**', (route) => route.fulfill({ status:200, contentType:'application/json', body:'[]' }));
  await page.goto('/alerts');

  const branch = page.getByLabel('Filter by branch');
  await expect(branch.locator('option')).toHaveCount(3);
  await expect(branch).toHaveCSS('width', '116px');
  await branch.selectOption('branch-2');
  await expect(page).toHaveURL(/branch_id=branch-2/);
  await expect(page.getByText('A Branch With A Long Display Name', { exact:true })).toBeVisible();

  await page.getByLabel('Clear branch filter').click();
  const source = page.getByLabel('Filter by source');
  await source.selectOption('branch_exterior');
  await expect(page).toHaveURL(/use_case=branch_exterior/);
  await expect(source).toHaveValue('branch_exterior');

  await page.getByRole('tab', { name:'History' }).click();
  await expect(page).toHaveURL(/group=HISTORY/);
  await expect(page.getByRole('tab', { name:'History' })).toHaveAttribute('aria-selected', 'true');

  const dateSummary = page.getByText('Date range', { exact:true });
  await dateSummary.click();
  const dates = page.locator('.alert-filter-dates');
  await expect(dates).toHaveAttribute('open', '');
  await page.keyboard.press('Escape');
  await expect(dates).not.toHaveAttribute('open', '');
  await dateSummary.click();
  await page.getByRole('heading', { name:'Alert Center' }).click();
  await expect(dates).not.toHaveAttribute('open', '');
});
