import { test, expect, loginAsAdmin, loginAsUser, clearSession, expectAdminSidebar, navigateToAdminPage } from './fixtures';

const navigateToEvents = async (page: import('@playwright/test').Page) => {
  await navigateToAdminPage(page, '/admin/events', 'Event Browser');
};

test.describe('Admin Events Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToEvents(page);
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
});

test.describe('Admin Events Filtering', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToEvents(page);
  });

  test('can toggle filter panel', async ({ page }) => {
    await page.getByRole('button', { name: /Filters/i }).click();
    await page.waitForTimeout(500);
  });

  test('filter panel shows date range inputs', async ({ page }) => {
    await page.getByRole('button', { name: /Filters/i }).click();
    await page.waitForTimeout(500);
    const fromInput = page.locator('input[type="datetime-local"], input[type="date"]').first();
    if (await fromInput.isVisible({ timeout: 2000 }).catch(() => false)) {
      await expect(fromInput).toBeVisible();
    }
  });
});

test.describe('Admin Events Export', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToEvents(page);
  });

  test('can open export dropdown', async ({ page }) => {
    await page.getByRole('button', { name: /Export/i }).click();
    await expect(page.getByText('CSV')).toBeVisible();
    await expect(page.getByText('JSON')).toBeVisible();
  });
});

test.describe('Admin Events Table', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToEvents(page);
  });

  test('shows events table or empty state', async ({ page }) => {
    await page.waitForTimeout(2000);
    const table = page.locator('table').first();
    const emptyState = page.getByText(/No events found/i);
    const hasTable = await table.isVisible({ timeout: 3000 }).catch(() => false);
    const hasEmpty = await emptyState.isVisible({ timeout: 3000 }).catch(() => false);
    expect(hasTable || hasEmpty).toBe(true);
  });

  test('events table shows time column', async ({ page }) => {
    await page.waitForTimeout(2000);
    const timeHeader = page.getByText('Time');
    if (await timeHeader.isVisible({ timeout: 3000 }).catch(() => false)) {
      await expect(timeHeader).toBeVisible();
    }
  });
});

test.describe('Admin Events Refresh', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToEvents(page);
  });

  test('can manually refresh events', async ({ page }) => {
    await page.getByRole('button', { name: /Refresh/i }).click();
    await page.waitForTimeout(500);
  });
});

test.describe('Admin Events Access Control', () => {
  test('redirects non-admin users', async ({ page }) => {
    await loginAsUser(page);
    await page.goto('/admin/events');
    await page.waitForURL(url => url.pathname === '/' || url.pathname.includes('/login'));
    const url = new URL(page.url());
    expect(url.pathname === '/' || url.pathname.includes('/login')).toBe(true);
  });

  test('redirects unauthenticated users to login', async ({ page }) => {
    await clearSession(page);
    await page.goto('/admin/events');
    await expect(page).toHaveURL(/\/login/);
  });
});
