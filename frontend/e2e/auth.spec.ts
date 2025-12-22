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

    await expect(page.getByRole('heading', { name: 'Sign in to your account' })).toBeVisible();
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test('prevents submission and shows validation for empty form', async ({ page }) => {
    await page.goto('/login');
    await page.waitForSelector('#username');

    // Click submit without filling any fields
    await page.click('button[type="submit"]');

    // Form should not submit - still on login page
    await expect(page).toHaveURL(/\/login/);

    // Browser focuses first invalid required field and shows validation
    const usernameInput = page.locator('#username');
    await expect(usernameInput).toBeFocused();

    // Check HTML5 validity state
    const isInvalid = await usernameInput.evaluate((el: HTMLInputElement) => !el.validity.valid);
    expect(isInvalid).toBe(true);

    // Verify validation message exists (browser shows "Please fill out this field" or similar)
    const validationMessage = await usernameInput.evaluate((el: HTMLInputElement) => el.validationMessage);
    expect(validationMessage.length).toBeGreaterThan(0);
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

    // Wait for Editor page content (router updates DOM before URL)
    await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
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

    // Wait for Settings page content (redirect target)
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
    await expect(page).toHaveURL(/\/settings/);
  });

  test('has link to registration page', async ({ page }) => {
    await page.goto('/login');
    await page.waitForSelector('#username');

    // Use specific text to avoid matching the Register button in header
    const registerLink = page.getByRole('link', { name: 'create a new account' });
    await expect(registerLink).toBeVisible();
  });

  test('can navigate to registration page', async ({ page }) => {
    await page.goto('/login');
    await page.waitForSelector('#username');

    // Click the specific link in the form, not the header button
    await page.getByRole('link', { name: 'create a new account' }).click();

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
    // Wait for Editor page content (router updates DOM before URL)
    await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
  });

  test('can logout from authenticated state', async ({ page }) => {
    // Open user dropdown (contains the logout button)
    const userDropdown = page.locator('.user-dropdown-container button').first();
    await expect(userDropdown).toBeVisible();
    await userDropdown.click();

    // Click logout button inside the dropdown
    const logoutButton = page.locator('button:has-text("Logout")').first();
    await expect(logoutButton).toBeVisible();
    await logoutButton.click();
    await expect(page).toHaveURL(/\/login/);
  });
});
