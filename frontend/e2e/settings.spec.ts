import { test, expect, type Page } from '@playwright/test';

async function login(page: Page, username = 'user', password = 'user123') {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.waitForSelector('#username');
  await page.fill('#username', username);
  await page.fill('#password', password);
  await page.click('button[type="submit"]');
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });
}

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible({ timeout: 10000 });
  });

  test('displays settings page with all tabs', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
    await expect(page.getByRole('button', { name: 'General' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Editor' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Notifications' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'View History' })).toBeVisible();
  });

  test('general tab shows theme selection', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'General Settings' })).toBeVisible();
    await expect(page.getByText('Theme')).toBeVisible();
    await expect(page.locator('#theme-select')).toBeVisible();
  });

  test('can open theme dropdown and see options', async ({ page }) => {
    await page.locator('#theme-select').click();

    await expect(page.getByText('Light')).toBeVisible();
    await expect(page.getByText('Dark')).toBeVisible();
    await expect(page.getByText('Auto (System)')).toBeVisible();
  });

  test('can change theme to dark', async ({ page }) => {
    await page.locator('#theme-select').click();
    await page.getByText('Dark').click();

    const hasDarkClass = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    );
    expect(hasDarkClass).toBe(true);
  });

  test('can change theme to light', async ({ page }) => {
    await page.locator('#theme-select').click();
    await page.getByText('Light').click();

    const hasDarkClass = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    );
    expect(hasDarkClass).toBe(false);
  });
});

test.describe('Settings Editor Tab', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible({ timeout: 10000 });
    await page.getByRole('button', { name: 'Editor' }).click();
  });

  test('shows editor settings section', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Editor Settings' })).toBeVisible();
    await expect(page.getByText('Editor Theme')).toBeVisible();
    await expect(page.getByText('Font Size')).toBeVisible();
    await expect(page.getByText('Tab Size')).toBeVisible();
  });

  test('shows editor theme dropdown', async ({ page }) => {
    await page.locator('#editor-theme-select').click();

    await expect(page.getByText('Auto (Follow App Theme)')).toBeVisible();
    await expect(page.getByText('One Dark')).toBeVisible();
    await expect(page.getByText('GitHub')).toBeVisible();
  });

  test('can change font size', async ({ page }) => {
    const fontSizeInput = page.locator('#font-size');
    await expect(fontSizeInput).toBeVisible();

    await fontSizeInput.fill('');
    await fontSizeInput.fill('16');
    await expect(fontSizeInput).toHaveValue('16');
  });

  test('can change tab size', async ({ page }) => {
    const tabSizeInput = page.locator('#tab-size');
    await expect(tabSizeInput).toBeVisible();

    await tabSizeInput.fill('');
    await tabSizeInput.fill('2');
    await expect(tabSizeInput).toHaveValue('2');
  });

  test('shows toggle options for editor preferences', async ({ page }) => {
    await expect(page.getByText('Use Tabs')).toBeVisible();
    await expect(page.getByText('Word Wrap')).toBeVisible();
    await expect(page.getByText('Show Line Numbers')).toBeVisible();
  });

  test('can toggle word wrap setting', async ({ page }) => {
    const wordWrapLabel = page.locator('label').filter({ hasText: 'Word Wrap' });
    const checkbox = wordWrapLabel.locator('input[type="checkbox"]');

    const initialState = await checkbox.isChecked();
    await wordWrapLabel.click();
    const newState = await checkbox.isChecked();

    expect(newState).toBe(!initialState);
  });
});

test.describe('Settings Notifications Tab', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible({ timeout: 10000 });
    await page.getByRole('button', { name: 'Notifications' }).click();
  });

  test('shows notification settings section', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Notification Settings' })).toBeVisible();
    await expect(page.getByText('Notification Types')).toBeVisible();
  });

  test('shows all notification type toggles', async ({ page }) => {
    await expect(page.getByText('Execution Completed')).toBeVisible();
    await expect(page.getByText('Execution Failed')).toBeVisible();
    await expect(page.getByText('System Updates')).toBeVisible();
    await expect(page.getByText('Security Alerts')).toBeVisible();
  });

  test('can toggle notification preferences', async ({ page }) => {
    const executionCompletedLabel = page.locator('label').filter({ hasText: 'Execution Completed' });
    const checkbox = executionCompletedLabel.locator('input[type="checkbox"]');

    const initialState = await checkbox.isChecked();
    await executionCompletedLabel.click();
    const newState = await checkbox.isChecked();

    expect(newState).toBe(!initialState);
  });
});

test.describe('Settings Save and History', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible({ timeout: 10000 });
  });

  test('shows save button', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Save Settings' })).toBeVisible();
  });

  test('can save settings', async ({ page }) => {
    await page.getByRole('button', { name: 'Editor' }).click();

    const fontSizeInput = page.locator('#font-size');
    const currentValue = await fontSizeInput.inputValue();
    const newValue = currentValue === '14' ? '15' : '14';

    await fontSizeInput.fill('');
    await fontSizeInput.fill(newValue);

    await page.getByRole('button', { name: 'Save Settings' }).click();

    const toast = page.locator('[class*="toast"]').first();
    await expect(toast).toBeVisible({ timeout: 5000 });
  });

  test('can open settings history modal', async ({ page }) => {
    await page.getByRole('button', { name: 'View History' }).click();

    await expect(page.getByRole('heading', { name: 'Settings History' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Close' })).toBeVisible();
  });

  test('can close settings history modal', async ({ page }) => {
    await page.getByRole('button', { name: 'View History' }).click();
    await expect(page.getByRole('heading', { name: 'Settings History' })).toBeVisible();

    await page.getByRole('button', { name: 'Close' }).click();

    await expect(page.getByRole('heading', { name: 'Settings History' })).not.toBeVisible();
  });

  test('history modal shows table headers', async ({ page }) => {
    await page.getByRole('button', { name: 'View History' }).click();

    await expect(page.getByText('Date')).toBeVisible();
    await expect(page.getByText('Field')).toBeVisible();
    await expect(page.getByText('Change')).toBeVisible();
  });
});

test.describe('Settings Access Control', () => {
  test('redirects to login when not authenticated', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });

    await page.goto('/settings');

    await expect(page).toHaveURL(/\/login/);
  });

  test('preserves settings page as redirect target after login', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });

    await page.goto('/settings');
    await expect(page).toHaveURL(/\/login/);

    await page.fill('#username', 'user');
    await page.fill('#password', 'user123');
    await page.click('button[type="submit"]');

    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible({ timeout: 10000 });
    await expect(page).toHaveURL(/\/settings/);
  });
});
