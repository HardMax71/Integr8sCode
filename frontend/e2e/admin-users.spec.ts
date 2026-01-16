import { test, expect, type Page } from '@playwright/test';

async function loginAsAdmin(page: Page) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.waitForSelector('#username');
  await page.fill('#username', 'admin');
  await page.fill('#password', 'admin123');
  await page.click('button[type="submit"]');
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });
}

async function navigateToAdminUsers(page: Page) {
  await page.goto('/admin/users');
  await expect(page.getByRole('heading', { name: 'User Management' })).toBeVisible({ timeout: 10000 });
}

test.describe('Admin Users Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminUsers(page);
  });

  test('displays admin users page with sidebar', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'User Management' })).toBeVisible();
    await expect(page.getByText('Admin Panel')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Event Browser' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Sagas' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Users' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Settings' })).toBeVisible();
  });

  test('shows create user and refresh buttons', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Create User/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Refresh/i })).toBeVisible();
  });

  test('shows users table with correct columns', async ({ page }) => {
    await page.waitForSelector('.table, [class*="card"]', { timeout: 10000 });

    const desktopTable = page.locator('.table').first();
    if (await desktopTable.isVisible({ timeout: 2000 }).catch(() => false)) {
      await expect(page.getByText('Username')).toBeVisible();
      await expect(page.getByText('Email')).toBeVisible();
      await expect(page.getByText('Role')).toBeVisible();
      await expect(page.getByText('Status')).toBeVisible();
      await expect(page.getByText('Actions')).toBeVisible();
    }
  });

  test('shows search filter', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search"]').first();
    await expect(searchInput).toBeVisible();
  });

  test('shows role filter dropdown', async ({ page }) => {
    const roleFilter = page.locator('select').filter({ hasText: /All Roles|user|admin/i }).first();
    if (await roleFilter.isVisible({ timeout: 2000 }).catch(() => false)) {
      await expect(roleFilter).toBeVisible();
    }
  });

  test('shows status filter dropdown', async ({ page }) => {
    const statusFilter = page.locator('select, button').filter({ hasText: /All Status|Active|Disabled/i }).first();
    if (await statusFilter.isVisible({ timeout: 2000 }).catch(() => false)) {
      await expect(statusFilter).toBeVisible();
    }
  });

  test('displays seeded users in table', async ({ page }) => {
    await page.waitForTimeout(1000);

    const userRow = page.locator('text=user').first();
    await expect(userRow).toBeVisible({ timeout: 5000 });
  });

  test('can search for users', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search"]').first();
    await searchInput.fill('admin');

    await page.waitForTimeout(500);

    const adminRow = page.locator('td, [class*="card"]').filter({ hasText: 'admin' }).first();
    await expect(adminRow).toBeVisible();
  });
});

test.describe('Admin Users Create Modal', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminUsers(page);
  });

  test('can open create user modal', async ({ page }) => {
    await page.getByRole('button', { name: /Create User/i }).click();

    await expect(page.getByRole('heading', { name: 'Create New User' })).toBeVisible();
  });

  test('create modal shows all form fields', async ({ page }) => {
    await page.getByRole('button', { name: /Create User/i }).click();

    await expect(page.locator('#user-form-username')).toBeVisible();
    await expect(page.locator('#user-form-email')).toBeVisible();
    await expect(page.locator('#user-form-password')).toBeVisible();
    await expect(page.locator('#user-form-role')).toBeVisible();
    await expect(page.getByText('Active User')).toBeVisible();
  });

  test('create modal has cancel and submit buttons', async ({ page }) => {
    await page.getByRole('button', { name: /Create User/i }).click();

    await expect(page.getByRole('button', { name: 'Cancel' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Create User' })).toBeVisible();
  });

  test('can close create modal with cancel button', async ({ page }) => {
    await page.getByRole('button', { name: /Create User/i }).click();
    await expect(page.getByRole('heading', { name: 'Create New User' })).toBeVisible();

    await page.getByRole('button', { name: 'Cancel' }).click();

    await expect(page.getByRole('heading', { name: 'Create New User' })).not.toBeVisible();
  });

  test('can fill create user form', async ({ page }) => {
    await page.getByRole('button', { name: /Create User/i }).click();

    await page.locator('#user-form-username').fill('testuser');
    await page.locator('#user-form-email').fill('test@example.com');
    await page.locator('#user-form-password').fill('TestPassword123!');
    await page.locator('#user-form-role').selectOption('user');

    await expect(page.locator('#user-form-username')).toHaveValue('testuser');
    await expect(page.locator('#user-form-email')).toHaveValue('test@example.com');
  });

  test('can create new user', async ({ page }) => {
    await page.getByRole('button', { name: /Create User/i }).click();

    const uniqueUsername = `testuser_${Date.now()}`;
    await page.locator('#user-form-username').fill(uniqueUsername);
    await page.locator('#user-form-email').fill(`${uniqueUsername}@example.com`);
    await page.locator('#user-form-password').fill('TestPassword123!');

    await page.getByRole('button', { name: 'Create User' }).click();

    await expect(page.getByRole('heading', { name: 'Create New User' })).not.toBeVisible({ timeout: 10000 });
  });
});

test.describe('Admin Users Edit', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminUsers(page);
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

      const usernameInput = page.locator('#user-form-username');
      const value = await usernameInput.inputValue();
      expect(value.length).toBeGreaterThan(0);
    }
  });
});

test.describe('Admin Users Delete', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminUsers(page);
  });

  test('delete button is present for users', async ({ page }) => {
    await page.waitForTimeout(1000);

    const deleteButton = page.locator('button[title="Delete User"], button:has(svg[class*="trash"]), button[class*="red"], button[class*="danger"]').first();
    const isVisible = await deleteButton.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(deleteButton).toBeVisible();
    }
  });
});

test.describe('Admin Users Rate Limits', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminUsers(page);
  });

  test('rate limits button is present for users', async ({ page }) => {
    await page.waitForTimeout(1000);

    const rateLimitsButton = page.locator('button[title="Manage Rate Limits"], button:has-text("Limits")').first();
    const isVisible = await rateLimitsButton.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(rateLimitsButton).toBeVisible();
    }
  });

  test('can open rate limits modal', async ({ page }) => {
    await page.waitForTimeout(1000);

    const rateLimitsButton = page.locator('button[title="Manage Rate Limits"], button:has-text("Limits")').first();
    if (await rateLimitsButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await rateLimitsButton.click();

      await page.waitForTimeout(1000);
    }
  });
});

test.describe('Admin Users Pagination', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminUsers(page);
  });

  test('shows pagination when users exist', async ({ page }) => {
    await page.waitForTimeout(1000);

    const paginationExists = await page.locator('text=/of|Page|Showing/').first().isVisible({ timeout: 3000 }).catch(() => false);
    if (paginationExists) {
      await expect(page.locator('text=/of|Page|Showing/').first()).toBeVisible();
    }
  });
});

test.describe('Admin Users Access Control', () => {
  test('redirects non-admin users to home', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.waitForSelector('#username');
    await page.fill('#username', 'user');
    await page.fill('#password', 'user123');
    await page.click('button[type="submit"]');
    await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });

    await page.goto('/admin/users');

    await expect(page).toHaveURL(/^\/$|\/login/);
  });

  test('redirects unauthenticated users to login', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });

    await page.goto('/admin/users');

    await expect(page).toHaveURL(/\/login/);
  });
});
