import { expect, test } from './fixtures';
import { ExecutionStatus, QueuePriority } from '#lib/api/types.gen.ts';
import { fieldTitle } from '#lib/formatters.ts';

test('the status and priority filters offer every value the API knows', async ({ adminPage }) => {
    await adminPage.goto('/admin/executions');
    await expect(adminPage.getByLabel(fieldTitle('status'), { exact: true }).locator('option')).toHaveText([
        'All',
        ...Object.values(ExecutionStatus),
    ]);
    await expect(adminPage.getByLabel(fieldTitle('priority'), { exact: true }).locator('option')).toHaveText([
        'All',
        ...Object.values(QueuePriority),
    ]);
});

test("a user's new execution shows in the table", async ({ adminPage, account, execution }) => {
    await adminPage.goto('/admin/executions');
    await adminPage.getByLabel(fieldTitle('user_id'), { exact: true }).fill(account.user_id);
    const table = adminPage.getByRole('table', { name: 'Executions' });
    await expect(table.getByRole('combobox', { name: `Priority for ${execution.execution_id}` })).toBeVisible();
    for (const key of ['execution_id', 'user_id', 'lang', 'status', 'priority', 'created_at']) {
        await expect(table.getByRole('columnheader', { name: fieldTitle(key), exact: true })).toBeVisible();
    }
});

test('refresh fetches the executions again', async ({ adminPage }) => {
    await adminPage.goto('/admin/executions');
    await expect(adminPage.getByRole('heading', { name: 'Execution Management' })).toBeVisible();
    const refreshed = adminPage.waitForResponse(/\/api\/v1\/admin\/executions\/\?/);
    await adminPage.getByRole('button', { name: 'Refresh' }).click();
    expect((await refreshed).ok()).toBe(true);
});
