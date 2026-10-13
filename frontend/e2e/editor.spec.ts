import { randomUUID } from 'node:crypto';
import type { ConsoleMessage } from '@playwright/test';
import { acceptDialog, expect, holdRequest, test } from './fixtures';
import { ExecutionStatus, type ResourceLimits } from '#lib/api/types.gen.ts';
import { fieldTitle } from '#lib/formatters.ts';

/** Whether a console message reports something the Content Security Policy blocked */
function isCspViolation(message: ConsoleMessage): boolean {
    return message.text().includes('Content Security Policy');
}

test('the editor shows the code area, the output panel and the run button', async ({ userPage }) => {
    await userPage.goto('/editor');
    await expect(userPage.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
    await expect(userPage.locator('.cm-editor')).toBeVisible();
    await expect(userPage.getByRole('heading', { name: 'Execution Output' })).toBeVisible();
    await expect(userPage.getByRole('button', { name: 'Run Script' })).toBeEnabled();
});

test('CodeMirror styles load under the CSP', async ({ userPage }) => {
    await userPage.goto('/editor');
    await expect(userPage.locator('.cm-gutters')).toHaveCSS('display', 'flex');
    expect((await userPage.consoleMessages()).filter(isCspViolation)).toEqual([]);
});

test('the language menu switches to another runtime', async ({ userPage, api }) => {
    const limits = (await (await api.get('/api/v1/k8s-limits')).json()) as ResourceLimits;
    const [lang, info] = Object.entries(limits.supported_runtimes).at(-1)!;
    const version = info.versions[0]!;
    await userPage.goto('/editor');
    const trigger = userPage.getByRole('button', { name: 'Select language and version' });
    await trigger.click();
    await userPage.getByRole('menuitem', { name: lang }).hover();
    await userPage
        .getByRole('menu', { name: `${lang} versions` })
        .getByRole('menuitemradio', { name: version })
        .click();
    await expect(trigger).toHaveText(`${lang} ${version}`);
});

test('the options panel shows the file actions and the saved scripts', async ({ userPage }) => {
    await userPage.goto('/editor');
    await userPage.getByRole('button', { name: 'Toggle Script Options' }).click();
    await expect(userPage.getByText('File Actions')).toBeVisible();
    for (const action of ['New', 'Upload', 'Save', 'Export']) {
        await expect(userPage.getByRole('button', { name: action, exact: true })).toBeVisible();
    }
    await expect(userPage.getByRole('heading', { name: 'Saved Scripts' })).toBeVisible();
});

test('the example button loads a script', async ({ userPage }) => {
    await userPage.goto('/editor');
    await userPage.getByRole('button', { name: 'Example', exact: true }).click();
    await expect(userPage.getByText(/^Loaded example script for /)).toBeVisible();
    await expect(userPage.locator('.cm-content')).not.toBeEmpty();
});

test('running a script shows its output, status and resource usage', async ({ userPage }) => {
    test.slow();
    const marker = randomUUID();
    await userPage.goto('/editor');
    await userPage.locator('.cm-content').fill(`print("${marker}")`);
    await userPage.getByRole('button', { name: 'Run Script' }).click();
    await expect(userPage.getByTestId('output-pre')).toHaveText(marker, { timeout: 20_000 });
    await expect(
        userPage.getByText(new RegExp(`^${fieldTitle('status')}\\s*${ExecutionStatus.COMPLETED}$`)),
    ).toBeVisible();
    for (const key of ['resource_usage', 'execution_time_wall_seconds', 'cpu_time_jiffies', 'peak_memory_kb']) {
        await expect(userPage.getByText(fieldTitle(key), { exact: true })).toBeVisible();
    }
    await expect(userPage.getByRole('button', { name: 'Run Script' })).toBeEnabled();
});

test('the run button is disabled while the execution starts', async ({ userPage }) => {
    await userPage.route('**/api/v1/execute', holdRequest);
    await userPage.goto('/editor');
    await userPage.locator('.cm-content').fill('print(1)');
    await userPage.getByRole('button', { name: 'Run Script' }).click();
    await expect(userPage.getByRole('button', { name: 'Executing...' })).toBeDisabled();
    await expect(userPage.getByText('Starting...')).toBeVisible();
});

test('a script saves under its name', async ({ userPage }) => {
    const name = `e2e-${randomUUID()}`;
    await userPage.goto('/editor');
    await userPage.locator('.cm-content').fill(`print("${name}")`);
    await userPage.getByLabel(fieldTitle('name')).fill(name);
    await userPage.getByRole('button', { name: 'Toggle Script Options' }).click();
    await userPage.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(userPage.getByText('Script saved successfully.')).toBeVisible();
});

test('a new script clears the name', async ({ userPage }) => {
    await userPage.goto('/editor');
    await userPage.getByLabel(fieldTitle('name')).fill(`e2e-${randomUUID()}`);
    await userPage.getByRole('button', { name: 'Toggle Script Options' }).click();
    await userPage.getByRole('button', { name: 'New', exact: true }).click();
    await expect(userPage.getByText('New script started.')).toBeVisible();
    await expect(userPage.getByLabel(fieldTitle('name'))).toHaveValue('');
});

test('a saved script loads back from the list', async ({ userPage }) => {
    const name = `e2e-${randomUUID()}`;
    await userPage.goto('/editor');
    await userPage.locator('.cm-content').fill(`print("${name}")`);
    await userPage.getByLabel(fieldTitle('name')).fill(name);
    await userPage.getByRole('button', { name: 'Toggle Script Options' }).click();
    await userPage.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(userPage.getByText('Script saved successfully.')).toBeVisible();
    await userPage.getByRole('button', { name: 'New', exact: true }).click();
    await expect(userPage.getByLabel(fieldTitle('name'))).toHaveValue('');
    await userPage.getByRole('button', { name: 'Show Saved Scripts' }).click();
    await userPage.getByText(name, { exact: true }).click();
    await expect(userPage.getByText(`Loaded script: ${name}`)).toBeVisible();
    await expect(userPage.getByLabel(fieldTitle('name'))).toHaveValue(name);
    await expect(userPage.locator('.cm-content')).toHaveText(`print("${name}")`);
});

test('a saved script can be deleted from the list', async ({ userPage }) => {
    const name = `e2e-${randomUUID()}`;
    await userPage.goto('/editor');
    await userPage.locator('.cm-content').fill(`print("${name}")`);
    await userPage.getByLabel(fieldTitle('name')).fill(name);
    await userPage.getByRole('button', { name: 'Toggle Script Options' }).click();
    await userPage.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(userPage.getByText('Script saved successfully.')).toBeVisible();
    await userPage.getByRole('button', { name: 'Show Saved Scripts' }).click();
    userPage.once('dialog', acceptDialog);
    await userPage.getByRole('button', { name: `Delete ${name}` }).click();
    await expect(userPage.getByText('Script deleted successfully.')).toBeVisible();
    await expect(userPage.getByText(name, { exact: true })).toHaveCount(0);
});

test('export downloads the script under its name', async ({ userPage }) => {
    const name = `e2e-${randomUUID()}`;
    await userPage.goto('/editor');
    await userPage.locator('.cm-content').fill(`print("${name}")`);
    await userPage.getByLabel(fieldTitle('name')).fill(name);
    await userPage.getByRole('button', { name: 'Toggle Script Options' }).click();
    const download = userPage.waitForEvent('download');
    await userPage.getByRole('button', { name: 'Export', exact: true }).click();
    expect((await download).suggestedFilename()).toContain(name);
});
