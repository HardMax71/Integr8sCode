import { test, expect, describeAdminCommonTests, describeAdminAccessControl, expectToastVisible } from './fixtures';

const PATH = '/admin/settings' as const;

const SETTINGS_SECTIONS = [
  {
    name: 'Execution Limits',
    labels: ['Max Timeout Seconds', 'Memory Limit', 'Cpu Limit', 'Max Concurrent Executions', 'Max Executions Per User'],
  },
  {
    name: 'Security Settings',
    labels: ['Password Min Length', 'Session Timeout Minutes', 'Max Login Attempts', 'Lockout Duration Minutes'],
  },
  { name: 'Monitoring Settings', labels: ['Metrics Retention Days', 'Log Level', 'Enable Tracing', 'Sampling Rate'] },
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
      for (const label of section.labels) {
        await expect(adminPage.getByLabel(label, { exact: true })).toBeVisible();
      }
    });
  }

  test('can modify max timeout value', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    const input = adminPage.getByLabel('Max Timeout Seconds');
    const current = await input.inputValue();
    await input.fill('120');
    await expect(input).toHaveValue('120');
    await input.fill(current);
  });

  test('log level select has correct options', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    const select = adminPage.getByLabel('Log Level');
    await expect(select.locator('option').first()).toBeAttached();
    const options = await select.locator('option').allTextContents();
    expect(options).toContain('DEBUG');
    expect(options).toContain('INFO');
    expect(options).toContain('WARNING');
    expect(options).toContain('ERROR');
  });

  test('can change log level', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    const select = adminPage.getByLabel('Log Level');
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
