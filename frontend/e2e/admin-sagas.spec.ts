import { test, expect, loginAsAdmin, loginAsUser, clearSession, expectAdminSidebar, navigateToAdminPage, expectRedirectToHome, expectRedirectToLogin } from './fixtures';

test.describe('Admin Sagas', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, '/admin/sagas');
  });

  test('displays saga management page with header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Saga Management' })).toBeVisible();
    await expect(page.getByText('Monitor and debug distributed transactions')).toBeVisible();
  });

  test('shows admin sidebar navigation', async ({ page }) => {
    await expectAdminSidebar(page);
  });

  test('sagas link is active in sidebar', async ({ page }) => {
    await expect(page.getByRole('link', { name: 'Sagas' })).toHaveClass(/bg-primary/);
  });

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
      // Verify filter was cleared
      await expect(searchInput).toHaveValue('');
    });
  });

  test.describe('Table', () => {
    test('shows sagas table or empty state', async ({ page }) => {
      await page.waitForTimeout(2000);
      const table = page.locator('table').first();
      const emptyState = page.getByText(/No sagas found/i);
      const hasTable = await table.isVisible({ timeout: 3000 }).catch(() => false);
      const hasEmpty = await emptyState.isVisible({ timeout: 3000 }).catch(() => false);
      expect(hasTable || hasEmpty).toBe(true);
    });

    test('sagas table shows state column when data exists', async ({ page }) => {
      const table = page.locator('table').first();
      // Only verify columns if table is visible (not empty state)
      if (await table.isVisible({ timeout: 3000 }).catch(() => false)) {
        await expect(page.getByRole('columnheader', { name: 'State' })).toBeVisible();
      }
    });
  });

  test.describe('Auto-Refresh', () => {
    test('auto-refresh control is visible', async ({ page }) => {
      await expect(page.getByText(/Auto-refresh/i)).toBeVisible();
    });

    test('can toggle auto-refresh', async ({ page }) => {
      const autoRefreshToggle = page.locator('input[type="checkbox"]').first();
      const initialState = await autoRefreshToggle.isChecked();
      await autoRefreshToggle.click();
      expect(await autoRefreshToggle.isChecked()).toBe(!initialState);
    });

    test('can change refresh rate', async ({ page }) => {
      const rateSelect = page.locator('#refresh-rate');
      await rateSelect.selectOption('10');
      await expect(rateSelect).toHaveValue('10');
    });
  });
});

test.describe('Admin Sagas Access Control', () => {
  test('redirects non-admin users to home', async ({ page }) => {
    await loginAsUser(page);
    await page.goto('/admin/sagas');
    await expectRedirectToHome(page);
  });

  test('redirects unauthenticated users to login', async ({ page }) => {
    await clearSession(page);
    await page.goto('/admin/sagas');
    await expectRedirectToLogin(page);
  });
});
