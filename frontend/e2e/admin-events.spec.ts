import { test, expect, loginAsAdmin, navigateToAdminPage, describeAdminCommonTests, describeAdminAccessControl, expectTableOrEmptyState, expectTableColumn } from './fixtures';

const PATH = '/admin/events' as const;
const EMPTY_PATTERN = /No events found/i;

test.describe('Admin Events', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, PATH);
  });

  describeAdminCommonTests(test, PATH);

  test('shows action buttons', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Filters/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Export/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Refresh/i })).toBeVisible();
  });

  test.describe('Filtering', () => {
    test('filter panel shows date range inputs', async ({ page }) => {
      await page.getByRole('button', { name: /Filters/i }).click();
      await expect(page.locator('input[type="datetime-local"], input[type="date"]').first()).toBeVisible();
    });
  });

  test.describe('Export', () => {
    test('can open export dropdown', async ({ page }) => {
      await page.getByRole('button', { name: /Export/i }).click();
      await expect(page.getByText('CSV')).toBeVisible();
      await expect(page.getByText('JSON')).toBeVisible();
    });
  });

  test.describe('Table', () => {
    test('shows events table or empty state', async ({ page }) => {
      await expectTableOrEmptyState(page, EMPTY_PATTERN);
    });

    test('shows Time column when data exists', async ({ page }) => {
      await expectTableColumn(page, 'Time', EMPTY_PATTERN);
    });
  });

  test.describe('Refresh', () => {
    test('can manually refresh events', async ({ page }) => {
      const [response] = await Promise.all([
        page.waitForResponse(resp => resp.url().includes('/events') && resp.status() === 200),
        page.getByRole('button', { name: /Refresh/i }).click(),
      ]);
      expect(response.ok()).toBe(true);
      await expect(page.getByRole('heading', { name: 'Event Browser' })).toBeVisible();
    });
  });
});

describeAdminAccessControl(test, PATH);
