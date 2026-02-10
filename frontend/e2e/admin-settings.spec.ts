import { test, expect, describeAdminCommonTests, describeAdminAccessControl, expectToastVisible } from './fixtures';

const PATH = '/admin/settings' as const;

const SETTINGS_SECTIONS = [
  { name: 'Execution Limits', inputs: ['#max-timeout', '#memory-limit', '#cpu-limit', '#max-concurrent'] },
  { name: 'Security Settings', inputs: ['#min-password', '#session-timeout', '#max-login', '#lockout-duration'] },
  { name: 'Monitoring Settings', inputs: ['#metrics-retention', '#log-level', '#enable-tracing', '#sampling-rate'] },
] as const;

test.describe('Admin Settings', () => {
  describeAdminCommonTests(test, PATH);

  test('shows configuration card', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await expect(adminPage.getByText('Configuration')).toBeVisible();
  });

  for (const section of SETTINGS_SECTIONS) {
    test(`shows ${section.name} section with all inputs`, async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await expect(adminPage.getByText(section.name)).toBeVisible();
      for (const input of section.inputs) {
        await expect(adminPage.locator(input)).toBeVisible();
      }
    });
  }

  test('can modify max timeout value', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    const input = adminPage.locator('#max-timeout');
    const current = await input.inputValue();
    await input.fill('120');
    await expect(input).toHaveValue('120');
    await input.fill(current);
  });

  test('log level select has correct options', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    // Wait for select to be visible and have options loaded
    await expect(adminPage.locator('#log-level')).toBeVisible();
    await expect(adminPage.locator('#log-level option').first()).toBeAttached();
    const options = await adminPage.locator('#log-level option').allTextContents();
    expect(options).toContain('DEBUG');
    expect(options).toContain('INFO');
    expect(options).toContain('WARNING');
    expect(options).toContain('ERROR');
  });

  test('can change log level', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    const select = adminPage.locator('#log-level');
    const original = await select.inputValue();
    await select.selectOption('DEBUG');
    await expect(select).toHaveValue('DEBUG');
    await select.selectOption(original);
  });

  test('shows save and reset buttons', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await expect(adminPage.getByRole('button', { name: 'Save Settings' })).toBeVisible();
    await expect(adminPage.getByRole('button', { name: 'Reset to Defaults' })).toBeVisible();
  });

  test('can save settings', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await adminPage.getByRole('button', { name: 'Save Settings' }).click();
    await expectToastVisible(adminPage);
  });
});

describeAdminAccessControl(test, PATH);
