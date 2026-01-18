import { test, expect, clearSession } from './fixtures';

const PATH = '/register';

async function navigateToRegister(page: import('@playwright/test').Page): Promise<void> {
  await clearSession(page);
  await page.goto(PATH);
  await page.waitForSelector('#username');
}

async function fillRegistrationForm(
  page: import('@playwright/test').Page,
  data: { username: string; email: string; password: string; confirmPassword: string }
): Promise<void> {
  await page.fill('#username', data.username);
  await page.fill('#email', data.email);
  await page.fill('#password', data.password);
  await page.fill('#confirm-password', data.confirmPassword);
}

test.describe('Registration', () => {
  test.beforeEach(async ({ page }) => {
    await navigateToRegister(page);
  });

  test('shows registration form with all required fields', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Create a new account' })).toBeVisible();
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#email')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('#confirm-password')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toHaveText('Create Account');
  });

  test('has link to login page', async ({ page }) => {
    await expect(page.getByRole('link', { name: 'sign in to your existing account' })).toBeVisible();
  });

  test('can navigate to login page', async ({ page }) => {
    await page.getByRole('link', { name: 'sign in to your existing account' }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test('validates required fields on empty submission', async ({ page }) => {
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL(/\/register/);
    const usernameInput = page.locator('#username');
    await expect(usernameInput).toBeFocused();
    const isInvalid = await usernameInput.evaluate((el: HTMLInputElement) => !el.validity.valid);
    expect(isInvalid).toBe(true);
  });

  test('shows error when passwords do not match', async ({ page }) => {
    await fillRegistrationForm(page, {
      username: 'testuser',
      email: 'test@example.com',
      password: 'Password123!',
      confirmPassword: 'DifferentPassword123!',
    });
    await page.click('button[type="submit"]');
    await expect(page.locator('p.text-red-600, p.text-red-400')).toContainText('Passwords do not match');
  });

  test('shows error when password is too short', async ({ page }) => {
    await fillRegistrationForm(page, {
      username: 'testuser',
      email: 'test@example.com',
      password: 'short',
      confirmPassword: 'short',
    });
    await page.click('button[type="submit"]');
    await expect(page.locator('p.text-red-600, p.text-red-400')).toContainText('at least 8 characters');
  });

  test('submits form and shows loading or redirects', async ({ page }) => {
    const uniqueId = Date.now();
    await fillRegistrationForm(page, {
      username: `newuser_${uniqueId}`,
      email: `newuser_${uniqueId}@example.com`,
      password: 'ValidPassword123!',
      confirmPassword: 'ValidPassword123!',
    });
    const submitButton = page.locator('button[type="submit"]');
    await submitButton.click();
    // Either see loading state OR redirect to login (both indicate successful submission)
    const loadingOrRedirect = await Promise.race([
      expect(submitButton).toContainText(/Registering/).then(() => 'loading'),
      expect(page).toHaveURL(/\/login/, { timeout: 10000 }).then(() => 'redirect'),
    ]).catch(() => 'timeout');
    expect(['loading', 'redirect']).toContain(loadingOrRedirect);
  });

  test('shows error for duplicate username', async ({ page }) => {
    await fillRegistrationForm(page, {
      username: 'user',
      email: 'unique@example.com',
      password: 'ValidPassword123!',
      confirmPassword: 'ValidPassword123!',
    });
    await page.click('button[type="submit"]');
    await expect(page.locator('p.text-red-600, p.text-red-400')).toBeVisible({ timeout: 5000 });
  });

  test('successful registration redirects to login', async ({ page }) => {
    const uniqueId = Date.now();
    await fillRegistrationForm(page, {
      username: `newuser_${uniqueId}`,
      email: `newuser_${uniqueId}@example.com`,
      password: 'ValidPassword123!',
      confirmPassword: 'ValidPassword123!',
    });
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL(/\/login/, { timeout: 10000 });
  });
});
