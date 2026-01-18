import { test, expect, describeAdminCommonTests, describeAdminAccessControl } from './fixtures';

const PATH = '/admin/users' as const;

test.describe('Admin Users', () => {
  describeAdminCommonTests(test, PATH);

  test('shows create user and refresh buttons', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await expect(adminPage.getByRole('button', { name: /Create User/i }).first()).toBeVisible();
    await expect(adminPage.getByRole('button', { name: /Refresh/i })).toBeVisible();
  });

  test('shows users table with correct columns', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await expect(adminPage.locator('text=Loading users...')).not.toBeVisible({ timeout: 15000 });
    await expect(adminPage.getByRole('columnheader', { name: 'Username' })).toBeVisible();
    await expect(adminPage.getByRole('columnheader', { name: 'Email' })).toBeVisible();
    await expect(adminPage.getByRole('columnheader', { name: 'Role' })).toBeVisible();
    await expect(adminPage.getByRole('columnheader', { name: 'Status' })).toBeVisible();
  });

  test('displays seeded users in table', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await expect(adminPage.locator('text=user').first()).toBeVisible({ timeout: 5000 });
  });

  test('can search for users', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    const searchInput = adminPage.locator('input[placeholder*="Search"]').first();
    await searchInput.fill('admin');
    await expect(adminPage.locator('td, [class*="card"]').filter({ hasText: 'admin' }).first()).toBeVisible({ timeout: 5000 });
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
      await adminPage.goto(PATH);
      await expect(adminPage.locator('text=Loading users...')).not.toBeVisible({ timeout: 15000 });
      const firstRow = adminPage.locator('table tbody tr').first();
      await expect(firstRow).toBeVisible({ timeout: 5000 });
      const editButton = firstRow.locator('button[title="Edit User"]');
      await editButton.click();
      await expect(adminPage.getByRole('heading', { name: 'Edit User' })).toBeVisible({ timeout: 5000 });
    });

    test('edit modal pre-fills user data', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await expect(adminPage.locator('text=Loading users...')).not.toBeVisible({ timeout: 15000 });
      const firstRow = adminPage.locator('table tbody tr').first();
      await expect(firstRow).toBeVisible({ timeout: 5000 });
      const editButton = firstRow.locator('button[title="Edit User"]');
      await editButton.click();
      await expect(adminPage.getByRole('heading', { name: 'Edit User' })).toBeVisible({ timeout: 5000 });
      const value = await adminPage.locator('#user-form-username').inputValue();
      expect(value.length).toBeGreaterThan(0);
    });
  });
});

describeAdminAccessControl(test, PATH);
