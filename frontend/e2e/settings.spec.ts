import { acceptDialog, expect, test } from './fixtures';
import { Theme } from '#lib/api/types.gen.ts';
import { fieldTitle } from '#lib/formatters.ts';

test('the settings page shows its tabs and the history button', async ({ userPage }) => {
    await userPage.goto('/settings');
    await expect(userPage.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
    const main = userPage.getByRole('main');
    for (const tab of ['General', fieldTitle('editor'), fieldTitle('notifications')]) {
        await expect(main.getByRole('button', { name: tab, exact: true })).toBeVisible();
    }
    await expect(userPage.getByRole('button', { name: 'View History' })).toBeVisible();
    await expect(userPage.getByRole('button', { name: 'Save Settings' })).toBeVisible();
});

test('the theme picker offers every theme and applies the pick at once', async ({ userPage }) => {
    await userPage.goto('/settings');
    await userPage.getByLabel(fieldTitle('theme'), { exact: true }).click();
    for (const theme of Object.values(Theme)) {
        await expect(userPage.getByRole('option', { name: theme, exact: true })).toBeVisible();
    }
    await userPage.getByRole('option', { name: Theme.DARK, exact: true }).click();
    await expect(userPage.locator('html')).toHaveClass(/\bdark\b/);
    await userPage.getByLabel(fieldTitle('theme'), { exact: true }).click();
    await userPage.getByRole('option', { name: Theme.LIGHT, exact: true }).click();
    await expect(userPage.locator('html')).not.toHaveClass(/\bdark\b/);
});

test('the editor tab edits font size, tab size and the toggles', async ({ userPage }) => {
    await userPage.goto('/settings');
    await userPage
        .getByRole('main')
        .getByRole('button', { name: fieldTitle('editor'), exact: true })
        .click();
    await expect(userPage.getByRole('heading', { name: fieldTitle('editor'), exact: true })).toBeVisible();
    const fontSize = userPage.getByLabel(fieldTitle('font_size'));
    await fontSize.fill('16');
    await expect(fontSize).toHaveValue('16');
    const tabSize = userPage.getByLabel(fieldTitle('tab_size'));
    await tabSize.selectOption('2');
    await expect(tabSize).toHaveValue('2');
    for (const key of ['use_tabs', 'word_wrap', 'show_line_numbers']) {
        const toggle = userPage.getByRole('checkbox', { name: fieldTitle(key) });
        const checked = await toggle.isChecked();
        await toggle.click();
        await expect(toggle).toBeChecked({ checked: !checked });
    }
});

test('the notifications tab toggles each notification type', async ({ userPage }) => {
    await userPage.goto('/settings');
    await userPage
        .getByRole('main')
        .getByRole('button', { name: fieldTitle('notifications'), exact: true })
        .click();
    await expect(userPage.getByRole('heading', { name: fieldTitle('notifications'), exact: true })).toBeVisible();
    for (const key of ['execution_completed', 'execution_failed', 'system_updates', 'security_alerts']) {
        const toggle = userPage.getByRole('checkbox', { name: fieldTitle(key) });
        const checked = await toggle.isChecked();
        await toggle.click();
        await expect(toggle).toBeChecked({ checked: !checked });
    }
});

test('a saved change shows in the history and can be restored', async ({ userPage }) => {
    await userPage.goto('/settings');
    await userPage
        .getByRole('main')
        .getByRole('button', { name: fieldTitle('editor'), exact: true })
        .click();
    const fontSize = userPage.getByLabel(fieldTitle('font_size'));
    await fontSize.fill((await fontSize.inputValue()) === '14' ? '15' : '14');
    await userPage.getByRole('button', { name: 'Save Settings' }).click();
    await expect(userPage.getByText('Settings saved successfully')).toBeVisible();

    await userPage.getByRole('button', { name: 'View History' }).click();
    const history = userPage.getByRole('dialog', { name: 'Settings History' });
    await expect(history).toBeVisible();
    userPage.once('dialog', acceptDialog);
    await history.getByRole('button', { name: 'Restore' }).first().click();
    await expect(userPage.getByText('Settings restored successfully')).toBeVisible();
});

test('the history dialog closes', async ({ userPage }) => {
    await userPage.goto('/settings');
    await userPage.getByRole('button', { name: 'View History' }).click();
    const history = userPage.getByRole('dialog', { name: 'Settings History' });
    await expect(history).toBeVisible();
    await history.getByRole('button', { name: 'Close', exact: true }).click();
    await expect(history).toBeHidden();
});
