import { test, expect, loginAsAdmin, loginAsUser, clearSession, expectAdminSidebar, navigateToAdminPage, expectRedirectToHome, expectRedirectToLogin } from './fixtures';

test.describe('Admin Events', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, '/admin/events');
  });

  test('displays event browser page with header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Event Browser' })).toBeVisible();
  });

  test('shows admin sidebar navigation', async ({ page }) => {
    await expectAdminSidebar(page);
  });

  test('event browser link is active in sidebar', async ({ page }) => {
    await expect(page.getByRole('link', { name: 'Event Browser' })).toHaveClass(/bg-primary/);
  });

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
      await page.waitForTimeout(2000);
      const table = page.locator('table').first();
      const emptyState = page.getByText(/No events found/i);
      const hasTable = await table.isVisible({ timeout: 3000 }).catch(() => false);
      const hasEmpty = await emptyState.isVisible({ timeout: 3000 }).catch(() => false);
      expect(hasTable || hasEmpty).toBe(true);
    });

    test('events table shows time column when data exists', async ({ page }) => {
      const table = page.locator('table').first();
      // Only verify columns if table is visible (not empty state)
      if (await table.isVisible({ timeout: 3000 }).catch(() => false)) {
        await expect(page.getByRole('columnheader', { name: 'Time' })).toBeVisible();
      }
    });
  });

  test.describe('Refresh', () => {
    test('can manually refresh events', async ({ page }) => {
      const refreshButton = page.getByRole('button', { name: /Refresh/i });

      // Click refresh and wait for the events API request to complete
      const [response] = await Promise.all([
        page.waitForResponse(resp => resp.url().includes('/events') && resp.status() === 200),
        refreshButton.click(),
      ]);

      // Verify the API call was made and succeeded
      expect(response.ok()).toBe(true);

      // Verify page still functional after refresh
      await expect(page.getByRole('heading', { name: 'Event Browser' })).toBeVisible();
    });
  });
});

test.describe('Admin Events Access Control', () => {
  test('redirects non-admin users to home', async ({ page }) => {
    await loginAsUser(page);
    await page.goto('/admin/events');
    await expectRedirectToHome(page);
  });

  test('redirects unauthenticated users to login', async ({ page }) => {
    await clearSession(page);
    await page.goto('/admin/events');
    await expectRedirectToLogin(page);
  });
});
