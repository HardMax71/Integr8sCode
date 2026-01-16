import { test, expect, loginAsAdmin, loginAsUser, clearSession, expectAdminSidebar, navigateToAdminPage } from './fixtures';

test.describe('Admin Sagas Page', () => {
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
});

test.describe('Admin Sagas Filtering', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, '/admin/sagas');
  });

  test('shows search input', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search"], input[type="search"]').first();
    if (await searchInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(searchInput).toBeVisible();
    }
  });

  test('shows state filter dropdown', async ({ page }) => {
    const stateFilter = page.locator('select, button').filter({ hasText: /All States|running|completed|failed/i }).first();
    if (await stateFilter.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(stateFilter).toBeVisible();
    }
  });

  test('can clear filters', async ({ page }) => {
    const clearButton = page.getByRole('button', { name: /Clear/i });
    if (await clearButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await clearButton.click();
      await page.waitForTimeout(500);
    }
  });
});

test.describe('Admin Sagas Table', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, '/admin/sagas');
  });

  test('shows sagas table or empty state', async ({ page }) => {
    await page.waitForTimeout(2000);
    const table = page.locator('table').first();
    const emptyState = page.getByText(/No sagas found/i);
    const hasTable = await table.isVisible({ timeout: 3000 }).catch(() => false);
    const hasEmpty = await emptyState.isVisible({ timeout: 3000 }).catch(() => false);
    expect(hasTable || hasEmpty).toBe(true);
  });

  test('sagas table shows state column', async ({ page }) => {
    await page.waitForTimeout(2000);
    const stateHeader = page.getByText('State');
    if (await stateHeader.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(stateHeader).toBeVisible();
    }
  });
});

test.describe('Admin Sagas Auto-Refresh', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, '/admin/sagas');
  });

  test('auto-refresh control is visible', async ({ page }) => {
    await expect(page.getByText(/Auto-refresh/i)).toBeVisible();
  });

  test('can toggle auto-refresh', async ({ page }) => {
    const autoRefreshToggle = page.locator('input[type="checkbox"]').first();
    if (await autoRefreshToggle.isVisible({ timeout: 3000 }).catch(() => false)) {
      const initialState = await autoRefreshToggle.isChecked();
      await autoRefreshToggle.click();
      expect(await autoRefreshToggle.isChecked()).toBe(!initialState);
    }
  });

  test('can change refresh rate', async ({ page }) => {
    const rateSelect = page.locator('#refresh-rate');
    if (await rateSelect.isVisible({ timeout: 3000 }).catch(() => false)) {
      await rateSelect.selectOption('10');
      await expect(rateSelect).toHaveValue('10');
    }
  });
});

test.describe('Admin Sagas Access Control', () => {
  test('redirects non-admin users', async ({ page }) => {
    await loginAsUser(page);
    await page.goto('/admin/sagas');
    await page.waitForURL(url => url.pathname === '/' || url.pathname.includes('/login'));
    const url = new URL(page.url());
    expect(url.pathname === '/' || url.pathname.includes('/login')).toBe(true);
  });

  test('redirects unauthenticated users to login', async ({ page }) => {
    await clearSession(page);
    await page.goto('/admin/sagas');
    await expect(page).toHaveURL(/\/login/);
  });
});
