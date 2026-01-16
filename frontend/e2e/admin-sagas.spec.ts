import { test, expect, loginAsAdmin, navigateToAdminPage, describeAdminCommonTests, describeAdminAccessControl, expectTableOrEmptyState, expectTableColumn } from './fixtures';

const PATH = '/admin/sagas' as const;
const EMPTY_PATTERN = /No sagas found/i;

test.describe('Admin Sagas', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, PATH);
  });

  describeAdminCommonTests(test, PATH);

  test('shows auto-refresh control', async ({ page }) => {
    await expect(page.getByText(/Auto-refresh/i)).toBeVisible();
  });

  test.describe('Filtering', () => {
    test('shows search input', async ({ page }) => {
      await expect(page.locator('input[placeholder*="Search"], input[type="search"]').first()).toBeVisible();
    });

    test('shows state filter dropdown', async ({ page }) => {
      await expect(page.locator('select, button').filter({ hasText: /All States|running|completed|failed/i }).first()).toBeVisible();
    });

    test('can clear filters', async ({ page }) => {
      const searchInput = page.locator('input[placeholder*="Search"], input[type="search"]').first();
      await searchInput.fill('test-filter');
      await page.getByRole('button', { name: /Clear/i }).click();
      await expect(searchInput).toHaveValue('');
    });
  });

  test.describe('Table', () => {
    test('shows sagas table or empty state', async ({ page }) => {
      await expectTableOrEmptyState(page, EMPTY_PATTERN);
    });

    test('shows State column when data exists', async ({ page }) => {
      await expectTableColumn(page, 'State', EMPTY_PATTERN);
    });
  });

  test.describe('Auto-Refresh', () => {
    test('can toggle auto-refresh', async ({ page }) => {
      const toggle = page.locator('input[type="checkbox"]').first();
      const initial = await toggle.isChecked();
      await toggle.click();
      expect(await toggle.isChecked()).toBe(!initial);
    });

    test('can change refresh rate', async ({ page }) => {
      const rateSelect = page.locator('#refresh-rate');
      await rateSelect.selectOption('10');
      await expect(rateSelect).toHaveValue('10');
    });
  });
});

describeAdminAccessControl(test, PATH);
