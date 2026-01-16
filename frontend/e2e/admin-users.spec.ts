import { test, expect, loginAsAdmin, loginAsUser, clearSession, expectAdminSidebar, navigateToAdminPage, expectRedirectToHome, expectRedirectToLogin } from './fixtures';

test.describe('Admin Users', () => {
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
    const mobileCard = page.locator('[class*="card"]').first();

    const isDesktop = await desktopTable.isVisible({ timeout: 2000 }).catch(() => false);
    const isMobile = await mobileCard.isVisible({ timeout: 2000 }).catch(() => false);

    // Fail if neither layout is visible
    expect(isDesktop || isMobile).toBe(true);

    if (isDesktop) {
      // Desktop: verify column headers
      await expect(page.getByRole('columnheader', { name: 'Username' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Email' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Role' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
    } else {
      // Mobile: verify data labels/fields are present in cards
      await expect(mobileCard.getByText(/username/i)).toBeVisible();
      await expect(mobileCard.getByText(/email/i)).toBeVisible();
      await expect(mobileCard.getByText(/role/i)).toBeVisible();
      await expect(mobileCard.getByText(/status|active|inactive/i)).toBeVisible();
    }
  });

  test('displays seeded users in table', async ({ page }) => {
    await expect(page.locator('text=user').first()).toBeVisible({ timeout: 5000 });
  });

  test('can search for users', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search"]').first();
    await searchInput.fill('admin');
    // Wait for search results to update - assertion timeout handles the wait
    await expect(page.locator('td, [class*="card"]').filter({ hasText: 'admin' }).first()).toBeVisible({ timeout: 5000 });
  });

  test.describe('Create Modal', () => {
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

  test.describe('Edit', () => {
    test('can open edit modal for existing user', async ({ page }) => {
      const editButton = page.locator('button[title="Edit User"], button:has-text("Edit")').first();
      // Seeded users should always be present, so edit button must exist
      await expect(editButton).toBeVisible({ timeout: 5000 });
      await editButton.click();
      await expect(page.getByRole('heading', { name: 'Edit User' })).toBeVisible({ timeout: 5000 });
    });

    test('edit modal pre-fills user data', async ({ page }) => {
      const editButton = page.locator('button[title="Edit User"], button:has-text("Edit")').first();
      // Seeded users should always be present, so edit button must exist
      await expect(editButton).toBeVisible({ timeout: 5000 });
      await editButton.click();
      await expect(page.getByRole('heading', { name: 'Edit User' })).toBeVisible({ timeout: 5000 });
      const value = await page.locator('#user-form-username').inputValue();
      expect(value.length).toBeGreaterThan(0);
    });
  });
});

test.describe('Admin Users Access Control', () => {
  test('redirects non-admin users to home', async ({ page }) => {
    await loginAsUser(page);
    await page.goto('/admin/users');
    await expectRedirectToHome(page);
  });

  test('redirects unauthenticated users to login', async ({ page }) => {
    await clearSession(page);
    await page.goto('/admin/users');
    await expectRedirectToLogin(page);
  });
});
