import { test, expect, describeAdminCommonTests, describeAdminAccessControl } from './fixtures';

const PATH = '/admin/users' as const;

// Helper to navigate and wait for users data to load
async function gotoAndWaitForUsers(adminPage: import('@playwright/test').Page) {
  await adminPage.goto(PATH);
  // Wait for table rows to appear (seeded users exist), not "Users (0)" empty state
  await adminPage.locator('table tbody tr').first().waitFor({ timeout: 15000 });
}

test.describe('Admin Users', () => {
  // Increase timeout for tests that wait for API data to load
  test.describe.configure({ timeout: 20000 });

  describeAdminCommonTests(test, PATH);

  test('shows create user and refresh buttons', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await expect(adminPage.getByRole('button', { name: /Create User/i }).first()).toBeVisible();
    await expect(adminPage.getByRole('button', { name: /Refresh/i })).toBeVisible();
  });

  test('shows users table with correct columns', async ({ adminPage }) => {
    await gotoAndWaitForUsers(adminPage);
    await expect(adminPage.locator('table').first()).toBeVisible();
    await expect(adminPage.getByRole('columnheader', { name: 'Username' })).toBeVisible();
    await expect(adminPage.getByRole('columnheader', { name: 'Email' })).toBeVisible();
    await expect(adminPage.getByRole('columnheader', { name: 'Role' })).toBeVisible();
    await expect(adminPage.getByRole('columnheader', { name: 'Status' })).toBeVisible();
  });

  test('displays seeded users in table', async ({ adminPage }) => {
    await gotoAndWaitForUsers(adminPage);
    await expect(adminPage.locator('text=user').first()).toBeVisible();
  });

  test('can search for users', async ({ adminPage }) => {
    await gotoAndWaitForUsers(adminPage);
    const searchInput = adminPage.locator('input[placeholder*="Search"]').first();
    await searchInput.fill('admin');
    await expect(adminPage.locator('td, [class*="card"]').filter({ hasText: 'admin' }).first()).toBeVisible();
  });

  test.describe('Create Modal', () => {
    test('can open create user modal', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await adminPage.getByRole('button', { name: /Create User/i }).first().click();
      await expect(adminPage.getByRole('heading', { name: 'Create New User' })).toBeVisible();
    });

    test('create modal shows all form fields', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await adminPage.getByRole('button', { name: /Create User/i }).first().click();
      await expect(adminPage.locator('#user-form-username')).toBeVisible();
      await expect(adminPage.locator('#user-form-email')).toBeVisible();
      await expect(adminPage.locator('#user-form-password')).toBeVisible();
      await expect(adminPage.locator('#user-form-role')).toBeVisible();
    });

    test('can close create modal with cancel button', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await adminPage.getByRole('button', { name: /Create User/i }).first().click();
      await expect(adminPage.getByRole('heading', { name: 'Create New User' })).toBeVisible();
      await adminPage.getByRole('button', { name: 'Cancel' }).click();
      await expect(adminPage.getByRole('heading', { name: 'Create New User' })).not.toBeVisible();
    });

    test('can fill and submit create user form', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await adminPage.getByRole('button', { name: /Create User/i }).first().click();
      const uniqueUsername = `testuser_${Date.now()}`;
      await adminPage.locator('#user-form-username').fill(uniqueUsername);
      await adminPage.locator('#user-form-email').fill(`${uniqueUsername}@example.com`);
      await adminPage.locator('#user-form-password').fill('TestPassword123!');
      await adminPage.getByLabel('Create New User').getByRole('button', { name: 'Create User' }).click();
      await expect(adminPage.getByRole('heading', { name: 'Create New User' })).not.toBeVisible({ timeout: 10000 });
    });
  });

  test.describe('Edit', () => {
    test('can open edit modal for existing user', async ({ adminPage }) => {
      await gotoAndWaitForUsers(adminPage);
      const editButton = adminPage.locator('table tbody tr').first().locator('button[title="Edit User"]');
      await expect(editButton).toBeVisible();
      await editButton.click();
      await expect(adminPage.getByRole('heading', { name: 'Edit User' })).toBeVisible();
    });

    test('edit modal pre-fills user data', async ({ adminPage }) => {
      await gotoAndWaitForUsers(adminPage);
      const editButton = adminPage.locator('table tbody tr').first().locator('button[title="Edit User"]');
      await expect(editButton).toBeVisible();
      await editButton.click();
      await expect(adminPage.getByRole('heading', { name: 'Edit User' })).toBeVisible();
      const value = await adminPage.locator('#user-form-username').inputValue();
      expect(value.length).toBeGreaterThan(0);
    });
  });
});

describeAdminAccessControl(test, PATH);
