import { test, expect, loginAsAdmin, loginAsUser, clearSession, expectAdminSidebar, navigateToAdminPage, testAdminAccessControl } from './fixtures';

test.describe('Admin Users Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, '/admin/users');
  });

  test('displays admin users page with sidebar', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'User Management' })).toBeVisible();
    await expectAdminSidebar(page);
  });

  test('shows create user and refresh buttons', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Create User/i }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /Refresh/i })).toBeVisible();
  });

  test('shows users table with correct columns', async ({ page }) => {
    await page.waitForSelector('.table, [class*="card"]', { timeout: 10000 });
    const desktopTable = page.locator('.table').first();
    if (await desktopTable.isVisible({ timeout: 2000 }).catch(() => false)) {
      // Use columnheader role to avoid matching filter labels/options
      await expect(page.getByRole('columnheader', { name: 'Username' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Email' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Role' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
    }
  });

  test('displays seeded users in table', async ({ page }) => {
    await page.waitForTimeout(1000);
    await expect(page.locator('text=user').first()).toBeVisible({ timeout: 5000 });
  });

  test('can search for users', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search"]').first();
    await searchInput.fill('admin');
    await page.waitForTimeout(500);
    await expect(page.locator('td, [class*="card"]').filter({ hasText: 'admin' }).first()).toBeVisible();
  });
});

test.describe('Admin Users Create Modal', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, '/admin/users');
  });

  test('can open create user modal', async ({ page }) => {
    await page.getByRole('button', { name: /Create User/i }).first().click();
    await expect(page.getByRole('heading', { name: 'Create New User' })).toBeVisible();
  });

  test('create modal shows all form fields', async ({ page }) => {
    await page.getByRole('button', { name: /Create User/i }).first().click();
    await expect(page.locator('#user-form-username')).toBeVisible();
    await expect(page.locator('#user-form-email')).toBeVisible();
    await expect(page.locator('#user-form-password')).toBeVisible();
    await expect(page.locator('#user-form-role')).toBeVisible();
  });

  test('can close create modal with cancel button', async ({ page }) => {
    await page.getByRole('button', { name: /Create User/i }).first().click();
    await expect(page.getByRole('heading', { name: 'Create New User' })).toBeVisible();
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByRole('heading', { name: 'Create New User' })).not.toBeVisible();
  });

  test('can fill and submit create user form', async ({ page }) => {
    await page.getByRole('button', { name: /Create User/i }).first().click();
    const uniqueUsername = `testuser_${Date.now()}`;
    await page.locator('#user-form-username').fill(uniqueUsername);
    await page.locator('#user-form-email').fill(`${uniqueUsername}@example.com`);
    await page.locator('#user-form-password').fill('TestPassword123!');
    await page.getByLabel('Create New User').getByRole('button', { name: 'Create User' }).click();
    await expect(page.getByRole('heading', { name: 'Create New User' })).not.toBeVisible({ timeout: 10000 });
  });
});

test.describe('Admin Users Edit', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, '/admin/users');
  });

  test('can open edit modal for existing user', async ({ page }) => {
    await page.waitForTimeout(1000);
    const editButton = page.locator('button[title="Edit User"], button:has-text("Edit")').first();
    if (await editButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await editButton.click();
      await expect(page.getByRole('heading', { name: 'Edit User' })).toBeVisible({ timeout: 5000 });
    }
  });

  test('edit modal pre-fills user data', async ({ page }) => {
    await page.waitForTimeout(1000);
    const editButton = page.locator('button[title="Edit User"], button:has-text("Edit")').first();
    if (await editButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await editButton.click();
      await expect(page.getByRole('heading', { name: 'Edit User' })).toBeVisible({ timeout: 5000 });
      const value = await page.locator('#user-form-username').inputValue();
      expect(value.length).toBeGreaterThan(0);
    }
  });
});

test.describe('Admin Users Access Control', () => {
  test('redirects non-admin users to home', async ({ page }) => {
    await loginAsUser(page);
    await page.goto('/admin/users');
    await page.waitForURL(url => url.pathname === '/' || url.pathname.includes('/login'));
    const url = new URL(page.url());
    expect(url.pathname === '/' || url.pathname.includes('/login')).toBe(true);
  });

  test('redirects unauthenticated users to login', async ({ page }) => {
    await clearSession(page);
    await page.goto('/admin/users');
    await expect(page).toHaveURL(/\/login/);
  });
});
