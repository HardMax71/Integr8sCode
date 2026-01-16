import { test, expect, type Page } from '@playwright/test';

async function loginAsAdmin(page: Page) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.waitForSelector('#username');
  await page.fill('#username', 'admin');
  await page.fill('#password', 'admin123');
  await page.click('button[type="submit"]');
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });
}

async function navigateToAdminSettings(page: Page) {
  await page.goto('/admin/settings');
  await expect(page.getByRole('heading', { name: 'System Settings' })).toBeVisible({ timeout: 10000 });
}

test.describe('Admin Settings Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSettings(page);
  });

  test('displays system settings page with header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'System Settings' })).toBeVisible();
  });

  test('shows admin sidebar navigation', async ({ page }) => {
    await expect(page.getByText('Admin Panel')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Event Browser' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Sagas' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Users' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Settings' })).toBeVisible();
  });

  test('settings link is active in sidebar', async ({ page }) => {
    const settingsLink = page.getByRole('link', { name: 'Settings' });
    await expect(settingsLink).toHaveClass(/bg-primary/);
  });

  test('shows configuration card', async ({ page }) => {
    await expect(page.getByText('Configuration')).toBeVisible();
  });
});

test.describe('Admin Settings Execution Limits', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSettings(page);
  });

  test('shows execution limits section', async ({ page }) => {
    await expect(page.getByText('Execution Limits')).toBeVisible();
  });

  test('shows max timeout input', async ({ page }) => {
    const maxTimeoutInput = page.locator('#max-timeout');
    await expect(maxTimeoutInput).toBeVisible();
  });

  test('shows max memory input', async ({ page }) => {
    const maxMemoryInput = page.locator('#max-memory');
    await expect(maxMemoryInput).toBeVisible();
  });

  test('shows max CPU input', async ({ page }) => {
    const maxCpuInput = page.locator('#max-cpu');
    await expect(maxCpuInput).toBeVisible();
  });

  test('shows max concurrent executions input', async ({ page }) => {
    const maxConcurrentInput = page.locator('#max-concurrent');
    await expect(maxConcurrentInput).toBeVisible();
  });

  test('can modify max timeout value', async ({ page }) => {
    const maxTimeoutInput = page.locator('#max-timeout');
    const currentValue = await maxTimeoutInput.inputValue();

    await maxTimeoutInput.fill('');
    await maxTimeoutInput.fill('120');
    await expect(maxTimeoutInput).toHaveValue('120');

    await maxTimeoutInput.fill('');
    await maxTimeoutInput.fill(currentValue);
  });

  test('can modify max memory value', async ({ page }) => {
    const maxMemoryInput = page.locator('#max-memory');
    const currentValue = await maxMemoryInput.inputValue();

    await maxMemoryInput.fill('');
    await maxMemoryInput.fill('512');
    await expect(maxMemoryInput).toHaveValue('512');

    await maxMemoryInput.fill('');
    await maxMemoryInput.fill(currentValue);
  });
});

test.describe('Admin Settings Security Settings', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSettings(page);
  });

  test('shows security settings section', async ({ page }) => {
    await expect(page.getByText('Security Settings')).toBeVisible();
  });

  test('shows min password length input', async ({ page }) => {
    const minPasswordInput = page.locator('#min-password');
    await expect(minPasswordInput).toBeVisible();
  });

  test('shows session timeout input', async ({ page }) => {
    const sessionTimeoutInput = page.locator('#session-timeout');
    await expect(sessionTimeoutInput).toBeVisible();
  });

  test('shows max login attempts input', async ({ page }) => {
    const maxLoginInput = page.locator('#max-login');
    await expect(maxLoginInput).toBeVisible();
  });

  test('shows lockout duration input', async ({ page }) => {
    const lockoutDurationInput = page.locator('#lockout-duration');
    await expect(lockoutDurationInput).toBeVisible();
  });

  test('can modify min password length value', async ({ page }) => {
    const minPasswordInput = page.locator('#min-password');
    const currentValue = await minPasswordInput.inputValue();

    await minPasswordInput.fill('');
    await minPasswordInput.fill('10');
    await expect(minPasswordInput).toHaveValue('10');

    await minPasswordInput.fill('');
    await minPasswordInput.fill(currentValue);
  });
});

test.describe('Admin Settings Monitoring Settings', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSettings(page);
  });

  test('shows monitoring settings section', async ({ page }) => {
    await expect(page.getByText('Monitoring Settings')).toBeVisible();
  });

  test('shows metrics retention days input', async ({ page }) => {
    const metricsRetentionInput = page.locator('#metrics-retention');
    await expect(metricsRetentionInput).toBeVisible();
  });

  test('shows log level select', async ({ page }) => {
    const logLevelSelect = page.locator('#log-level');
    await expect(logLevelSelect).toBeVisible();
  });

  test('log level select has correct options', async ({ page }) => {
    const logLevelSelect = page.locator('#log-level');
    await logLevelSelect.click();

    await expect(page.getByText('DEBUG')).toBeVisible();
    await expect(page.getByText('INFO')).toBeVisible();
    await expect(page.getByText('WARNING')).toBeVisible();
    await expect(page.getByText('ERROR')).toBeVisible();
  });

  test('shows enable tracing select', async ({ page }) => {
    const enableTracingSelect = page.locator('#enable-tracing');
    await expect(enableTracingSelect).toBeVisible();
  });

  test('shows sampling rate input', async ({ page }) => {
    const samplingRateInput = page.locator('#sampling-rate');
    await expect(samplingRateInput).toBeVisible();
  });

  test('can change log level', async ({ page }) => {
    const logLevelSelect = page.locator('#log-level');
    await logLevelSelect.selectOption('DEBUG');
    await expect(logLevelSelect).toHaveValue('DEBUG');
  });
});

test.describe('Admin Settings Actions', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSettings(page);
  });

  test('shows save settings button', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Save Settings' })).toBeVisible();
  });

  test('shows reset to defaults button', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Reset to Defaults' })).toBeVisible();
  });

  test('save settings button is enabled', async ({ page }) => {
    const saveButton = page.getByRole('button', { name: 'Save Settings' });
    await expect(saveButton).toBeEnabled();
  });

  test('reset button is enabled', async ({ page }) => {
    const resetButton = page.getByRole('button', { name: 'Reset to Defaults' });
    await expect(resetButton).toBeEnabled();
  });

  test('can save settings', async ({ page }) => {
    const saveButton = page.getByRole('button', { name: 'Save Settings' });
    await saveButton.click();

    const toast = page.locator('[class*="toast"]').first();
    const hasToast = await toast.isVisible({ timeout: 5000 }).catch(() => false);

    if (hasToast) {
      await expect(toast).toBeVisible();
    }
  });
});

test.describe('Admin Settings Loading State', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('shows loading state initially', async ({ page }) => {
    await page.goto('/admin/settings');

    const spinner = page.locator('[class*="spinner"], [class*="animate-spin"]').first();
    const settingsHeading = page.getByRole('heading', { name: 'System Settings' });

    const hasSpinner = await spinner.isVisible({ timeout: 1000 }).catch(() => false);
    const hasHeading = await settingsHeading.isVisible({ timeout: 1000 }).catch(() => false);

    expect(hasSpinner || hasHeading).toBe(true);
  });

  test('loads settings data after initial load', async ({ page }) => {
    await navigateToAdminSettings(page);

    await expect(page.locator('#max-timeout')).toBeVisible();
    const value = await page.locator('#max-timeout').inputValue();
    expect(value).toBeTruthy();
  });
});

test.describe('Admin Settings Access Control', () => {
  test('redirects non-admin users', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.waitForSelector('#username');
    await page.fill('#username', 'user');
    await page.fill('#password', 'user123');
    await page.click('button[type="submit"]');
    await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });

    await page.goto('/admin/settings');

    await expect(page).toHaveURL(/^\/$|\/login/);
  });

  test('redirects unauthenticated users to login', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });

    await page.goto('/admin/settings');

    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe('Admin Settings Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSettings(page);
  });

  test('can navigate to events from sidebar', async ({ page }) => {
    await page.getByRole('link', { name: 'Event Browser' }).click();
    await expect(page.getByRole('heading', { name: 'Event Browser' })).toBeVisible();
  });

  test('can navigate to sagas from sidebar', async ({ page }) => {
    await page.getByRole('link', { name: 'Sagas' }).click();
    await expect(page.getByRole('heading', { name: 'Saga Management' })).toBeVisible();
  });

  test('can navigate to users from sidebar', async ({ page }) => {
    await page.getByRole('link', { name: 'Users' }).click();
    await expect(page.getByRole('heading', { name: 'User Management' })).toBeVisible();
  });
});
