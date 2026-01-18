import { test, expect, describeAdminCommonTests, describeAdminAccessControl, expectTableOrEmptyState, expectTableColumn } from './fixtures';

const PATH = '/admin/sagas' as const;
const EMPTY_PATTERN = /No sagas found/i;

test.describe('Admin Sagas', () => {
  describeAdminCommonTests(test, PATH);

  test('shows auto-refresh control', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await expect(adminPage.getByText(/Auto-refresh/i)).toBeVisible();
  });

  test.describe('Filtering', () => {
    test('shows search input', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await expect(adminPage.locator('input[placeholder*="Search"], input[type="search"]').first()).toBeVisible();
    });

    test('shows state filter dropdown', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await expect(adminPage.locator('select, button').filter({ hasText: /All States|running|completed|failed/i }).first()).toBeVisible();
    });

    test('can clear filters', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      const searchInput = adminPage.locator('input[placeholder*="Search"], input[type="search"]').first();
      await searchInput.fill('test-filter');
      await adminPage.getByRole('button', { name: /Clear/i }).click();
      await expect(searchInput).toHaveValue('');
    });
  });

  test.describe('Table', () => {
    test('shows sagas table or empty state', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await expectTableOrEmptyState(adminPage, EMPTY_PATTERN);
    });

    test('shows State column when data exists', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await expectTableColumn(adminPage, 'State', EMPTY_PATTERN);
    });
  });

  test.describe('Auto-Refresh', () => {
    test('can toggle auto-refresh', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      const toggle = adminPage.locator('input[type="checkbox"]').first();
      const initial = await toggle.isChecked();
      await toggle.click();
      expect(await toggle.isChecked()).toBe(!initial);
    });

    test('can change refresh rate', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      const rateSelect = adminPage.locator('#refresh-rate');
      await rateSelect.selectOption('10');
      await expect(rateSelect).toHaveValue('10');
    });
  });
});

describeAdminAccessControl(test, PATH);
