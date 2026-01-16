import { test, expect, loginAsAdmin, navigateToAdminPage, describeAdminCommonTests, describeAdminAccessControl, expectToastVisible } from './fixtures';

const PATH = '/admin/settings' as const;

const SETTINGS_SECTIONS = [
  { name: 'Execution Limits', inputs: ['#max-timeout', '#max-memory', '#max-cpu', '#max-concurrent'] },
  { name: 'Security Settings', inputs: ['#min-password', '#session-timeout', '#max-login', '#lockout-duration'] },
  { name: 'Monitoring Settings', inputs: ['#metrics-retention', '#log-level', '#enable-tracing', '#sampling-rate'] },
] as const;

test.describe('Admin Settings', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminPage(page, PATH);
  });

  describeAdminCommonTests(test, PATH);

  test('shows configuration card', async ({ page }) => {
    await expect(page.getByText('Configuration')).toBeVisible();
  });

  for (const section of SETTINGS_SECTIONS) {
    test(`shows ${section.name} section with all inputs`, async ({ page }) => {
      await expect(page.getByText(section.name)).toBeVisible();
      for (const input of section.inputs) {
        await expect(page.locator(input)).toBeVisible();
      }
    });
  }

  test('can modify max timeout value', async ({ page }) => {
    const input = page.locator('#max-timeout');
    const current = await input.inputValue();
    await input.fill('120');
    await expect(input).toHaveValue('120');
    await input.fill(current);
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

  test('shows save and reset buttons', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Save Settings' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reset to Defaults' })).toBeVisible();
  });

  test('can save settings', async ({ page }) => {
    await page.getByRole('button', { name: 'Save Settings' }).click();
    await expectToastVisible(page);
  });
});

describeAdminAccessControl(test, PATH);
