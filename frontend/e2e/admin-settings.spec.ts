import { test, expect, loginAsAdmin, navigateToAdminPage, describeAdminCommonTests, describeAdminAccessControl, expectToastVisible } from './fixtures';

const PATH = '/admin/settings' as const;

test.describe('Admin Settings', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, PATH);
  });

  describeAdminCommonTests(test, PATH);

  test('shows configuration card', async ({ page }) => {
    await expect(page.getByText('Configuration')).toBeVisible();
  });

  test.describe('Execution Limits', () => {
    test('shows execution limits section', async ({ page }) => {
      await expect(page.getByText('Execution Limits')).toBeVisible();
    });

    test('shows all execution limit inputs', async ({ page }) => {
      await expect(page.locator('#max-timeout')).toBeVisible();
      await expect(page.locator('#max-memory')).toBeVisible();
      await expect(page.locator('#max-cpu')).toBeVisible();
      await expect(page.locator('#max-concurrent')).toBeVisible();
    });

    test('can modify max timeout value', async ({ page }) => {
      const input = page.locator('#max-timeout');
      const current = await input.inputValue();
      await input.fill('120');
      await expect(input).toHaveValue('120');
      await input.fill(current);
    });
  });

  test.describe('Security Settings', () => {
    test('shows security settings section', async ({ page }) => {
      await expect(page.getByText('Security Settings')).toBeVisible();
    });

    test('shows all security inputs', async ({ page }) => {
      await expect(page.locator('#min-password')).toBeVisible();
      await expect(page.locator('#session-timeout')).toBeVisible();
      await expect(page.locator('#max-login')).toBeVisible();
      await expect(page.locator('#lockout-duration')).toBeVisible();
    });
  });

  test.describe('Monitoring Settings', () => {
    test('shows monitoring settings section', async ({ page }) => {
      await expect(page.getByText('Monitoring Settings')).toBeVisible();
    });

    test('shows monitoring inputs and selects', async ({ page }) => {
      await expect(page.locator('#metrics-retention')).toBeVisible();
      await expect(page.locator('#log-level')).toBeVisible();
      await expect(page.locator('#enable-tracing')).toBeVisible();
      await expect(page.locator('#sampling-rate')).toBeVisible();
    });

    test('log level select has correct options', async ({ page }) => {
      const options = await page.locator('#log-level option').allTextContents();
      expect(options).toContain('DEBUG');
      expect(options).toContain('INFO');
      expect(options).toContain('WARNING');
      expect(options).toContain('ERROR');
    });

    test('can change log level', async ({ page }) => {
      await page.locator('#log-level').selectOption('DEBUG');
      await expect(page.locator('#log-level')).toHaveValue('DEBUG');
    });
  });

  test.describe('Actions', () => {
    test('shows save and reset buttons', async ({ page }) => {
      await expect(page.getByRole('button', { name: 'Save Settings' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Reset to Defaults' })).toBeVisible();
    });

    test('can save settings', async ({ page }) => {
      await page.getByRole('button', { name: 'Save Settings' }).click();
      await expectToastVisible(page);
    });
  });

  test.describe('Navigation', () => {
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
});

describeAdminAccessControl(test, PATH);
