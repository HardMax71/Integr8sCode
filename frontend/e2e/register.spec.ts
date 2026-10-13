import { randomUUID } from 'node:crypto';
import { expect, test } from './fixtures';
import { fieldTitle } from '#lib/formatters.ts';

test('the registration page shows its form', async ({ page }) => {
    await page.goto('/register');
    await expect(page.getByRole('heading', { name: 'Create a new account' })).toBeVisible();
    for (const name of ['username', 'email', 'password', 'confirm_password']) {
        await expect(page.getByLabel(fieldTitle(name), { exact: true })).toBeVisible();
    }
    await expect(page.getByRole('button', { name: 'Create Account' })).toBeVisible();
});

test('the registration page links to login', async ({ page }) => {
    await page.goto('/register');
    await page.getByRole('link', { name: 'sign in to your existing account' }).click();
    await expect(page).toHaveURL(/\/login/);
});

test('an empty registration form marks its fields as required', async ({ page }) => {
    await page.goto('/register');
    await page.getByRole('button', { name: 'Create Account' }).click();
    await expect(page).toHaveURL(/\/register/);
    await expect(page.getByLabel(fieldTitle('username'), { exact: true })).toHaveAccessibleDescription('Required');
});

test('passwords that differ are flagged on the confirmation', async ({ page }) => {
    await page.goto('/register');
    await page.getByLabel(fieldTitle('username'), { exact: true }).fill(`e2e-${randomUUID()}`);
    await page.getByLabel(fieldTitle('email'), { exact: true }).fill(`${randomUUID()}@example.com`);
    await page.getByLabel(fieldTitle('password'), { exact: true }).fill(randomUUID());
    await page.getByLabel(fieldTitle('confirm_password'), { exact: true }).fill(randomUUID());
    await page.getByRole('button', { name: 'Create Account' }).click();
    const confirmation = page.getByLabel(fieldTitle('confirm_password'), { exact: true });
    await expect(confirmation).toHaveAccessibleDescription('Passwords do not match');
    await expect(confirmation).toHaveAttribute('aria-invalid', 'true');
});

test('a short password is flagged with the minimum length', async ({ page }) => {
    await page.goto('/register');
    await page.getByLabel(fieldTitle('password'), { exact: true }).fill('short');
    await page.getByLabel(fieldTitle('confirm_password'), { exact: true }).fill('short');
    await page.getByRole('button', { name: 'Create Account' }).click();
    await expect(page.getByLabel(fieldTitle('password'), { exact: true })).toHaveAccessibleDescription(
        'Must be at least 8 characters',
    );
});

test('a taken username shows the error above the form', async ({ page, account }) => {
    const password = randomUUID();
    await page.goto('/register');
    await page.getByLabel(fieldTitle('username'), { exact: true }).fill(account.username);
    await page.getByLabel(fieldTitle('email'), { exact: true }).fill(`${randomUUID()}@example.com`);
    await page.getByLabel(fieldTitle('password'), { exact: true }).fill(password);
    await page.getByLabel(fieldTitle('confirm_password'), { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Create Account' }).click();
    await expect(page.getByTestId('error-message')).toBeVisible();
    await expect(page).toHaveURL(/\/register/);
});

test('registering leads to the login page', async ({ page }) => {
    const username = `e2e-${randomUUID()}`;
    const password = randomUUID();
    await page.goto('/register');
    await page.getByLabel(fieldTitle('username'), { exact: true }).fill(username);
    await page.getByLabel(fieldTitle('email'), { exact: true }).fill(`${username}@example.com`);
    await page.getByLabel(fieldTitle('password'), { exact: true }).fill(password);
    await page.getByLabel(fieldTitle('confirm_password'), { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Create Account' }).click();
    await expect(page.getByText('Registration successful! Please log in.')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
});
