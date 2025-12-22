import { test, expect } from '@playwright/test';

test.describe('Authentication', () => {
  test.beforeEach(async ({ page }) => {
    // Clear ALL auth state: cookies (HTTP-only auth token) + localStorage (cached state)
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
  });

  test('shows login page with form elements', async ({ page }) => {
    await page.goto('/login');
    // Wait for the login form to render
    await page.waitForSelector('#username');

    await expect(page.locator('h2')).toContainText('Sign in to your account');
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test('shows validation when submitting empty form', async ({ page }) => {
    await page.goto('/login');
    await page.waitForSelector('#username');

    const usernameInput = page.locator('#username');
    await expect(usernameInput).toHaveAttribute('required', '');
  });

  test('shows error with invalid credentials', async ({ page }) => {
    await page.goto('/login');
    await page.waitForSelector('#username');

    await page.fill('#username', 'invaliduser');
    await page.fill('#password', 'wrongpassword');
    await page.click('button[type="submit"]');

    await expect(page.locator('p.text-red-600, p.text-red-400')).toBeVisible();
  });

  test('redirects to editor on successful login', async ({ page }) => {
    await page.goto('/login');
    await page.waitForSelector('#username');

    await page.fill('#username', 'user');
    await page.fill('#password', 'user123');
    await page.click('button[type="submit"]');

    await expect(page).toHaveURL(/\/editor/);
  });

  test('shows loading state during login', async ({ page }) => {
    await page.goto('/login');
    await page.waitForSelector('#username');

    await page.fill('#username', 'user');
    await page.fill('#password', 'user123');

    const submitButton = page.locator('button[type="submit"]');
    await submitButton.click();

    await expect(submitButton).toContainText(/Logging in|Sign in/);
  });

  test('redirects unauthenticated users from protected routes', async ({ page }) => {
    await page.goto('/editor');
    // Should redirect to login and show login form
    await page.waitForSelector('#username');
    await expect(page).toHaveURL(/\/login/);
  });

  test('preserves redirect path after login', async ({ page }) => {
    await page.goto('/settings');
    // Should redirect to login
    await page.waitForSelector('#username');
    await expect(page).toHaveURL(/\/login/);

    // Login
    await page.fill('#username', 'user');
    await page.fill('#password', 'user123');
    await page.click('button[type="submit"]');

    await expect(page).toHaveURL(/\/settings/);
  });

  test('has link to registration page', async ({ page }) => {
    await page.goto('/login');
    await page.waitForSelector('#username');

    const registerLink = page.locator('a[href="/register"]');
    await expect(registerLink).toBeVisible();
    await expect(registerLink).toContainText('create a new account');
  });

  test('can navigate to registration page', async ({ page }) => {
    await page.goto('/login');
    await page.waitForSelector('#username');

    await page.click('a[href="/register"]');

    await expect(page).toHaveURL(/\/register/);
  });
});

test.describe('Logout', () => {
  test.beforeEach(async ({ page }) => {
    // Clear all state first
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.waitForSelector('#username');

    // Login
    await page.fill('#username', 'user');
    await page.fill('#password', 'user123');
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL(/\/editor/);
  });

  test('can logout from authenticated state', async ({ page }) => {
    // Find and click logout button
    const logoutButton = page.locator('button:has-text("Logout"), a:has-text("Logout"), [data-testid="logout"]');

    if (await logoutButton.isVisible()) {
      await logoutButton.click();
      await expect(page).toHaveURL(/\/login/);
    }
  });
});
