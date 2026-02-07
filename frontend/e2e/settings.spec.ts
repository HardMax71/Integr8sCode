import { test, expect, expectToastVisible, describeAuthRequired, clearSession, TEST_USERS } from './fixtures';

const PATH = '/settings';
const HEADING = 'Settings';

test.describe('Settings Page', () => {
  test('displays settings page with all tabs', async ({ userPage }) => {
    await userPage.goto(PATH);
    await expect(userPage.getByRole('heading', { name: HEADING, level: 1 })).toBeVisible();
    await expect(userPage.getByRole('button', { name: 'General' })).toBeVisible();
    await expect(userPage.getByRole('button', { name: 'Editor' })).toBeVisible();
    await expect(userPage.locator('main').getByText('Notifications')).toBeVisible();
    await expect(userPage.getByRole('button', { name: 'View History' })).toBeVisible();
  });

  test('general tab shows theme selection', async ({ userPage }) => {
    await userPage.goto(PATH);
    await expect(userPage.getByRole('heading', { name: 'General Settings' })).toBeVisible();
    await expect(userPage.getByText('Theme')).toBeVisible();
    await expect(userPage.locator('#theme-select')).toBeVisible();
  });

  test('can open theme dropdown and see options', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.locator('#theme-select').click();
    await expect(userPage.getByRole('button', { name: 'Light', exact: true })).toBeVisible();
    await expect(userPage.getByRole('button', { name: 'Dark', exact: true })).toBeVisible();
    await expect(userPage.getByRole('button', { name: 'Auto (System)', exact: true })).toBeVisible();
  });

  test('can change theme to dark', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.locator('#theme-select').click();
    await userPage.getByText('Dark').click();
    const hasDarkClass = await userPage.evaluate(() => document.documentElement.classList.contains('dark'));
    expect(hasDarkClass).toBe(true);
  });

  test('can change theme to light', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.locator('#theme-select').click();
    await userPage.getByText('Light').click();
    const hasDarkClass = await userPage.evaluate(() => document.documentElement.classList.contains('dark'));
    expect(hasDarkClass).toBe(false);
  });
});

test.describe('Settings Editor Tab', () => {
  test('shows editor settings section', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: 'Editor' }).click();
    await expect(userPage.getByRole('heading', { name: 'Editor Settings' })).toBeVisible();
    await expect(userPage.getByText('Editor Theme')).toBeVisible();
    await expect(userPage.getByText('Font Size')).toBeVisible();
    await expect(userPage.getByText('Tab Size')).toBeVisible();
  });

  test('shows editor theme dropdown', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: 'Editor' }).click();
    await userPage.locator('#editor-theme-select').click();
    await expect(userPage.getByRole('button', { name: 'Auto (Follow App Theme)', exact: true })).toBeVisible();
    await expect(userPage.getByRole('button', { name: 'One Dark', exact: true })).toBeVisible();
  });

  test('can change font size', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: 'Editor' }).click();
    const fontSizeInput = userPage.locator('#font-size');
    await fontSizeInput.fill('');
    await fontSizeInput.fill('16');
    await expect(fontSizeInput).toHaveValue('16');
  });

  test('can change tab size', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: 'Editor' }).click();
    const tabSizeInput = userPage.locator('#tab-size');
    await tabSizeInput.fill('');
    await tabSizeInput.fill('2');
    await expect(tabSizeInput).toHaveValue('2');
  });

  test('can toggle word wrap setting', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: 'Editor' }).click();
    const wordWrapLabel = userPage.locator('label').filter({ hasText: 'Word Wrap' });
    const checkbox = wordWrapLabel.locator('input[type="checkbox"]');
    const initialState = await checkbox.isChecked();
    await wordWrapLabel.click();
    expect(await checkbox.isChecked()).toBe(!initialState);
  });
});

test.describe('Settings Notifications Tab', () => {
  test('shows notification settings section', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.locator('main').getByText('Notifications').click();
    await expect(userPage.getByRole('heading', { name: 'Notification Settings' })).toBeVisible();
    await expect(userPage.getByText('Notification Types')).toBeVisible();
  });

  test('shows all notification type toggles', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.locator('main').getByText('Notifications').click();
    await expect(userPage.getByText('Execution Completed')).toBeVisible();
    await expect(userPage.getByText('Execution Failed')).toBeVisible();
    await expect(userPage.getByText('System Updates')).toBeVisible();
    await expect(userPage.getByText('Security Alerts')).toBeVisible();
  });

  test('can toggle notification preferences', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.locator('main').getByText('Notifications').click();
    const label = userPage.locator('label').filter({ hasText: 'Execution Completed' });
    const checkbox = label.locator('input[type="checkbox"]');
    const initialState = await checkbox.isChecked();
    await label.click();
    expect(await checkbox.isChecked()).toBe(!initialState);
  });
});

test.describe('Settings Save and History', () => {
  test('shows save button', async ({ userPage }) => {
    await userPage.goto(PATH);
    await expect(userPage.getByRole('button', { name: 'Save Settings' })).toBeVisible();
  });

  test('can save settings', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: 'Editor' }).click();
    const fontSizeInput = userPage.locator('#font-size');
    const currentValue = await fontSizeInput.inputValue();
    await fontSizeInput.fill(currentValue === '14' ? '15' : '14');
    await userPage.getByRole('button', { name: 'Save Settings' }).click();
    await expectToastVisible(userPage);
  });

  test('can open settings history modal', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: 'View History' }).click();
    await expect(userPage.getByRole('heading', { name: 'Settings History' })).toBeVisible();
  });

  test('can close settings history modal', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: 'View History' }).click();
    await userPage.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(userPage.getByRole('heading', { name: 'Settings History' })).not.toBeVisible();
  });

  test('can restore settings from history', async ({ userPage }) => {
    // First make a change and save to ensure history exists
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: 'Editor' }).click();
    const fontSizeInput = userPage.locator('#font-size');
    const currentValue = await fontSizeInput.inputValue();
    await fontSizeInput.fill(currentValue === '14' ? '15' : '14');
    await userPage.getByRole('button', { name: 'Save Settings' }).click();
    await expectToastVisible(userPage);

    // Open history and look for restore button
    await userPage.getByRole('button', { name: 'View History' }).click();
    await expect(userPage.getByRole('heading', { name: 'Settings History' })).toBeVisible();

    const restoreBtn = userPage.getByRole('button', { name: 'Restore' }).first();
    if (await restoreBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      // Accept the confirm dialog
      userPage.on('dialog', dialog => dialog.accept());
      await restoreBtn.click();
      await expectToastVisible(userPage);
    }
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
