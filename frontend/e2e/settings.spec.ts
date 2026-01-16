import { test, expect, loginAsUser, navigateToPage, expectToastVisible, describeAuthRequired, clearSession, TEST_USERS } from './fixtures';

const PATH = '/settings';
const HEADING = 'Settings';

test.describe('Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
    await navigateToPage(page, PATH, HEADING);
  });

  test('displays settings page with all tabs', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'General' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Editor' })).toBeVisible();
    await expect(page.locator('main').getByText('Notifications')).toBeVisible();
    await expect(page.getByRole('button', { name: 'View History' })).toBeVisible();
  });

  test('general tab shows theme selection', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'General Settings' })).toBeVisible();
    await expect(page.getByText('Theme')).toBeVisible();
    await expect(page.locator('#theme-select')).toBeVisible();
  });

  test('can open theme dropdown and see options', async ({ page }) => {
    await page.locator('#theme-select').click();
    await expect(page.getByRole('button', { name: 'Light', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Dark', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Auto (System)', exact: true })).toBeVisible();
  });

  test('can change theme to dark', async ({ page }) => {
    await page.locator('#theme-select').click();
    await page.getByText('Dark').click();
    const hasDarkClass = await page.evaluate(() => document.documentElement.classList.contains('dark'));
    expect(hasDarkClass).toBe(true);
  });

  test('can change theme to light', async ({ page }) => {
    await page.locator('#theme-select').click();
    await page.getByText('Light').click();
    const hasDarkClass = await page.evaluate(() => document.documentElement.classList.contains('dark'));
    expect(hasDarkClass).toBe(false);
  });
});

test.describe('Settings Editor Tab', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
    await navigateToPage(page, PATH, HEADING);
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
    await expect(page.getByRole('button', { name: 'Auto (Follow App Theme)', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'One Dark', exact: true })).toBeVisible();
  });

  test('can change font size', async ({ page }) => {
    const fontSizeInput = page.locator('#font-size');
    await fontSizeInput.fill('');
    await fontSizeInput.fill('16');
    await expect(fontSizeInput).toHaveValue('16');
  });

  test('can change tab size', async ({ page }) => {
    const tabSizeInput = page.locator('#tab-size');
    await tabSizeInput.fill('');
    await tabSizeInput.fill('2');
    await expect(tabSizeInput).toHaveValue('2');
  });

  test('can toggle word wrap setting', async ({ page }) => {
    const wordWrapLabel = page.locator('label').filter({ hasText: 'Word Wrap' });
    const checkbox = wordWrapLabel.locator('input[type="checkbox"]');
    const initialState = await checkbox.isChecked();
    await wordWrapLabel.click();
    expect(await checkbox.isChecked()).toBe(!initialState);
  });
});

test.describe('Settings Notifications Tab', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
    await navigateToPage(page, PATH, HEADING);
    await page.locator('main').getByText('Notifications').click();
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
    const label = page.locator('label').filter({ hasText: 'Execution Completed' });
    const checkbox = label.locator('input[type="checkbox"]');
    const initialState = await checkbox.isChecked();
    await label.click();
    expect(await checkbox.isChecked()).toBe(!initialState);
  });
});

test.describe('Settings Save and History', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
    await navigateToPage(page, PATH, HEADING);
  });

  test('shows save button', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Save Settings' })).toBeVisible();
  });

  test('can save settings', async ({ page }) => {
    await page.getByRole('button', { name: 'Editor' }).click();
    const fontSizeInput = page.locator('#font-size');
    const currentValue = await fontSizeInput.inputValue();
    await fontSizeInput.fill(currentValue === '14' ? '15' : '14');
    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expectToastVisible(page);
  });

  test('can open settings history modal', async ({ page }) => {
    await page.getByRole('button', { name: 'View History' }).click();
    await expect(page.getByRole('heading', { name: 'Settings History' })).toBeVisible();
  });

  test('can close settings history modal', async ({ page }) => {
    await page.getByRole('button', { name: 'View History' }).click();
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Settings History' })).not.toBeVisible();
  });
});

test.describe('Settings Access Control', () => {
  test('redirects to login when not authenticated', async ({ page }) => {
    await clearSession(page);
    await page.goto(PATH);
    await expect(page).toHaveURL(/\/login/);
  });

  test('preserves settings page as redirect target after login', async ({ page }) => {
    await clearSession(page);
    await page.goto(PATH);
    await expect(page).toHaveURL(/\/login/);
    await page.fill('#username', TEST_USERS.user.username);
    await page.fill('#password', TEST_USERS.user.password);
    await page.click('button[type="submit"]');
    await expect(page.getByRole('heading', { name: HEADING, level: 1 })).toBeVisible({ timeout: 10000 });
  });
});
