import { test, expect, loginAsAdmin, navigateToAdminPage, describeAdminCommonTests, describeAdminAccessControl } from './fixtures';

const PATH = '/admin/users' as const;

test.describe('Admin Users', () => {
  test.describe.configure({ timeout: 30000 });

  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, PATH);
  });

  describeAdminCommonTests(test, PATH);

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
    expect(isDesktop || isMobile).toBe(true);

    if (isDesktop) {
      await expect(page.getByRole('columnheader', { name: 'Username' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Email' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Role' })).toBeVisible();
      await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
    } else {
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
      const firstRow = page.locator('table tbody tr').first();
      await expect(firstRow).toBeVisible({ timeout: 10000 });
      const editButton = firstRow.locator('button[title="Edit User"]');
      await editButton.click();
      await expect(page.getByRole('heading', { name: 'Edit User' })).toBeVisible({ timeout: 5000 });
    });

    test('edit modal pre-fills user data', async ({ page }) => {
      const firstRow = page.locator('table tbody tr').first();
      await expect(firstRow).toBeVisible({ timeout: 10000 });
      const editButton = firstRow.locator('button[title="Edit User"]');
      await editButton.click();
      await expect(page.getByRole('heading', { name: 'Edit User' })).toBeVisible({ timeout: 5000 });
      const value = await page.locator('#user-form-username').inputValue();
      expect(value.length).toBeGreaterThan(0);
    });
  });
});

describeAdminAccessControl(test, PATH);
