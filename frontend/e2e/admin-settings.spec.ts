import { expect, test } from './fixtures';
import { LogLevel } from '#lib/api/types.gen.ts';
import { zSystemSettingsSchemaInput } from '#lib/api/zod.gen.ts';
import { fieldTitle } from '#lib/formatters.ts';

test('the form has a labelled control for every system setting', async ({ adminPage }) => {
    await adminPage.goto('/admin/settings');
    for (const section of ['Execution Limits', 'Security Settings', 'Monitoring Settings']) {
        await expect(adminPage.getByRole('heading', { name: section })).toBeVisible();
    }
    for (const key of Object.keys(zSystemSettingsSchemaInput.shape)) {
        await expect(adminPage.getByLabel(fieldTitle(key), { exact: true })).toBeVisible();
    }
    await expect(adminPage.getByRole('button', { name: 'Reset to Defaults' })).toBeVisible();
});

test('the log level offers every level the API knows', async ({ adminPage }) => {
    await adminPage.goto('/admin/settings');
    await expect(adminPage.getByLabel(fieldTitle('log_level')).locator('option')).toHaveText(Object.values(LogLevel));
});

test('saving the loaded settings confirms it', async ({ adminPage }) => {
    await adminPage.goto('/admin/settings');
    await adminPage.getByRole('button', { name: 'Save Settings' }).click();
    await expect(adminPage.getByText('Settings saved successfully')).toBeVisible();
});
