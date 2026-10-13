import { randomUUID } from 'node:crypto';
import { expect, test } from './fixtures';
import { UserRole } from '#lib/api/types.gen.ts';
import { fieldTitle } from '#lib/formatters.ts';

test('the users page shows the create and refresh buttons', async ({ adminPage }) => {
    await adminPage.goto('/admin/users');
    await expect(adminPage.getByRole('button', { name: 'Create User' })).toBeVisible();
    await expect(adminPage.getByRole('button', { name: 'Refresh' })).toBeVisible();
});

test('a search finds an account and the table shows its columns', async ({ adminPage, account }) => {
    await adminPage.goto('/admin/users');
    await adminPage.getByLabel(fieldTitle('search'), { exact: true }).fill(account.username);
    const row = adminPage.getByRole('row').filter({ hasText: account.username });
    await expect(row).toBeVisible();
    await expect(row).toContainText(UserRole.USER);
    for (const key of ['username', 'email', 'role', 'created_at', 'is_active']) {
        await expect(adminPage.getByRole('columnheader', { name: fieldTitle(key), exact: true })).toBeVisible();
    }
});

test('the create dialog shows the account fields and cancels', async ({ adminPage }) => {
    await adminPage.goto('/admin/users');
    await adminPage.getByRole('button', { name: 'Create User' }).click();
    const dialog = adminPage.getByRole('dialog', { name: 'Create New User' });
    for (const key of ['username', 'email', 'password', 'role']) {
        await expect(dialog.getByLabel(fieldTitle(key))).toBeVisible();
    }
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toBeHidden();
});

test('a created user shows up in the table', async ({ adminPage }) => {
    const username = `e2e-${randomUUID()}`;
    await adminPage.goto('/admin/users');
    await adminPage.getByRole('button', { name: 'Create User' }).click();
    const dialog = adminPage.getByRole('dialog', { name: 'Create New User' });
    await dialog.getByLabel(fieldTitle('username')).fill(username);
    await dialog.getByLabel(fieldTitle('email')).fill(`${username}@example.com`);
    await dialog.getByLabel(fieldTitle('password')).fill(randomUUID());
    await dialog.getByRole('button', { name: 'Create User' }).click();
    await expect(dialog).toBeHidden();
    await adminPage.getByLabel(fieldTitle('search'), { exact: true }).fill(username);
    await expect(adminPage.getByRole('row').filter({ hasText: username })).toBeVisible();
});

test('the edit dialog opens with the account filled in', async ({ adminPage, account }) => {
    await adminPage.goto('/admin/users');
    await adminPage.getByLabel(fieldTitle('search'), { exact: true }).fill(account.username);
    await adminPage
        .getByRole('row')
        .filter({ hasText: account.username })
        .getByRole('button', { name: 'Edit User' })
        .click();
    const dialog = adminPage.getByRole('dialog', { name: 'Edit User' });
    await expect(dialog.getByLabel(fieldTitle('username'))).toHaveValue(account.username);
    await expect(dialog.getByLabel(fieldTitle('email'))).toHaveValue(account.email);
});
