import { test, expect } from '@playwright/test';

test.describe('Registration', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/register');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
  });

  test('shows registration form with all required fields', async ({ page }) => {
    await page.waitForSelector('#username');

    await expect(page.getByRole('heading', { name: 'Create a new account' })).toBeVisible();
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#email')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('#confirm-password')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toHaveText('Create Account');
  });

  test('has link to login page', async ({ page }) => {
    await page.waitForSelector('#username');

    const loginLink = page.getByRole('link', { name: 'sign in to your existing account' });
    await expect(loginLink).toBeVisible();
  });

  test('can navigate to login page', async ({ page }) => {
    await page.waitForSelector('#username');

    await page.getByRole('link', { name: 'sign in to your existing account' }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test('validates required fields on empty submission', async ({ page }) => {
    await page.waitForSelector('#username');

    await page.click('button[type="submit"]');

    await expect(page).toHaveURL(/\/register/);

    const usernameInput = page.locator('#username');
    await expect(usernameInput).toBeFocused();

    const isInvalid = await usernameInput.evaluate((el: HTMLInputElement) => !el.validity.valid);
    expect(isInvalid).toBe(true);
  });

  test('shows error when passwords do not match', async ({ page }) => {
    await page.waitForSelector('#username');

    await page.fill('#username', 'testuser');
    await page.fill('#email', 'test@example.com');
    await page.fill('#password', 'Password123!');
    await page.fill('#confirm-password', 'DifferentPassword123!');
    await page.click('button[type="submit"]');

    await expect(page.locator('p.text-red-600, p.text-red-400')).toContainText('Passwords do not match');
  });

  test('shows error when password is too short', async ({ page }) => {
    await page.waitForSelector('#username');

    await page.fill('#username', 'testuser');
    await page.fill('#email', 'test@example.com');
    await page.fill('#password', 'short');
    await page.fill('#confirm-password', 'short');
    await page.click('button[type="submit"]');

    await expect(page.locator('p.text-red-600, p.text-red-400')).toContainText('at least 8 characters');
  });

  test('shows loading state during registration', async ({ page }) => {
    await page.waitForSelector('#username');

    await page.fill('#username', `newuser_${Date.now()}`);
    await page.fill('#email', `newuser_${Date.now()}@example.com`);
    await page.fill('#password', 'ValidPassword123!');
    await page.fill('#confirm-password', 'ValidPassword123!');

    const submitButton = page.locator('button[type="submit"]');
    await submitButton.click();

    await expect(submitButton).toContainText(/Registering|Create Account/);
  });

  test('shows error for duplicate username', async ({ page }) => {
    await page.waitForSelector('#username');

    await page.fill('#username', 'user');
    await page.fill('#email', 'unique@example.com');
    await page.fill('#password', 'ValidPassword123!');
    await page.fill('#confirm-password', 'ValidPassword123!');
    await page.click('button[type="submit"]');

    await expect(page.locator('p.text-red-600, p.text-red-400')).toBeVisible({ timeout: 5000 });
  });

  test('successful registration redirects to login', async ({ page }) => {
    await page.waitForSelector('#username');

    const uniqueId = Date.now();
    await page.fill('#username', `newuser_${uniqueId}`);
    await page.fill('#email', `newuser_${uniqueId}@example.com`);
    await page.fill('#password', 'ValidPassword123!');
    await page.fill('#confirm-password', 'ValidPassword123!');
    await page.click('button[type="submit"]');

    await expect(page).toHaveURL(/\/login/, { timeout: 10000 });
  });
});
