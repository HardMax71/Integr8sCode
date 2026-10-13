import { randomUUID } from 'node:crypto';
import { expect, holdRequest, test } from './fixtures';
import { fieldTitle } from '#lib/formatters.ts';

test('the login page shows its form', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: 'Sign in to your account' })).toBeVisible();
    await expect(page.getByLabel(fieldTitle('username'))).toBeVisible();
    await expect(page.getByLabel(fieldTitle('password'))).toBeVisible();
    await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
});

test('an empty login form marks its fields as required', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByLabel(fieldTitle('username'))).toHaveAccessibleDescription('Required');
    await expect(page.getByLabel(fieldTitle('password'))).toHaveAccessibleDescription('Required');
});

test('unknown credentials show the error above the form', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel(fieldTitle('username')).fill(`e2e-${randomUUID()}`);
    await page.getByLabel(fieldTitle('password')).fill(randomUUID());
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByTestId('error-message')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
});

test('signing in opens the editor', async ({ page, account }) => {
    await page.goto('/login');
    await page.getByLabel(fieldTitle('username')).fill(account.username);
    await page.getByLabel(fieldTitle('password')).fill(account.password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByText('Login successful! Welcome back.')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
    await expect(page).toHaveURL(/\/editor/);
});

test('the sign in button shows progress while the request is pending', async ({ page, account }) => {
    await page.route('**/api/v1/auth/login', holdRequest);
    await page.goto('/login');
    await page.getByLabel(fieldTitle('username')).fill(account.username);
    await page.getByLabel(fieldTitle('password')).fill(account.password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('button', { name: 'Logging in...' })).toBeDisabled();
});

test('signing in returns to the page that asked for it', async ({ page, account }) => {
    await page.goto('/settings');
    await expect(page).toHaveURL(/\/login\?redirect=%2Fsettings/);
    await page.getByLabel(fieldTitle('username')).fill(account.username);
    await page.getByLabel(fieldTitle('password')).fill(account.password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
    await expect(page).toHaveURL(/\/settings$/);
});

test('the login page links to registration', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('link', { name: 'create a new account' }).click();
    await expect(page).toHaveURL(/\/register/);
});

test('logging out returns to the login page', async ({ userPage }) => {
    await userPage.goto('/editor');
    await userPage.getByRole('button', { name: 'User menu' }).click();
    await userPage.getByRole('menuitem', { name: 'Logout' }).click();
    await expect(userPage).toHaveURL(/\/login/);
    await userPage.goto('/editor');
    await expect(userPage).toHaveURL(/\/login/);
});
