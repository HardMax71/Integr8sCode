import { test, expect, clearSession, loginAsUser, TEST_USERS } from './fixtures';

const PATH = '/login';

async function navigateToLogin(page: import('@playwright/test').Page): Promise<void> {
  await clearSession(page);
  await page.goto(PATH);
  await page.waitForSelector('#username');
}

async function fillLoginForm(page: import('@playwright/test').Page, username: string, password: string): Promise<void> {
  await page.fill('#username', username);
  await page.fill('#password', password);
  await page.click('button[type="submit"]');
}

test.describe('Authentication', () => {
  test.beforeEach(async ({ page }) => {
    await navigateToLogin(page);
  });

  test('shows login page with form elements', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Sign in to your account' })).toBeVisible();
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test('prevents submission and shows validation for empty form', async ({ page }) => {
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL(/\/login/);
    const usernameInput = page.locator('#username');
    await expect(usernameInput).toBeFocused();
    const isInvalid = await usernameInput.evaluate((el: HTMLInputElement) => !el.validity.valid);
    expect(isInvalid).toBe(true);
    const validationMessage = await usernameInput.evaluate((el: HTMLInputElement) => el.validationMessage);
    expect(validationMessage.length).toBeGreaterThan(0);
  });

  test('shows error with invalid credentials', async ({ page }) => {
    await fillLoginForm(page, 'invaliduser', 'wrongpassword');
    await expect(page.locator('p.text-red-600, p.text-red-400')).toBeVisible();
  });

  test('redirects to editor on successful login', async ({ page }) => {
    await fillLoginForm(page, TEST_USERS.user.username, TEST_USERS.user.password);
    await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
    await expect(page).toHaveURL(/\/editor/);
  });

  test('shows loading state during login', async ({ page }) => {
    await page.fill('#username', TEST_USERS.user.username);
    await page.fill('#password', TEST_USERS.user.password);
    const submitButton = page.locator('button[type="submit"]');
    await submitButton.click();
    await expect(submitButton).toContainText(/Logging in|Sign in/);
  });

  test('redirects unauthenticated users from protected routes', async ({ page }) => {
    await page.goto('/editor');
    await page.waitForSelector('#username');
    await expect(page).toHaveURL(/\/login/);
  });

  test('preserves redirect path after login', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForSelector('#username');
    await expect(page).toHaveURL(/\/login/);
    await fillLoginForm(page, TEST_USERS.user.username, TEST_USERS.user.password);
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
    await expect(page).toHaveURL(/\/settings/);
  });

  test('has link to registration page', async ({ page }) => {
    const registerLink = page.getByRole('link', { name: 'create a new account' });
    await expect(registerLink).toBeVisible();
  });

  test('can navigate to registration page', async ({ page }) => {
    await page.getByRole('link', { name: 'create a new account' }).click();
    await expect(page).toHaveURL(/\/register/);
  });
});

test.describe('Logout', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
  });

  test('can logout from authenticated state', async ({ page }) => {
    const userDropdown = page.locator('.user-dropdown-container button').first();
    await expect(userDropdown).toBeVisible();
    await userDropdown.click();
    const logoutButton = page.locator('button:has-text("Logout")').first();
    await expect(logoutButton).toBeVisible();
    await logoutButton.click();
    await expect(page).toHaveURL(/\/login/);
  });
});
