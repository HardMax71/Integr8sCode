import { expect, test } from './fixtures';
import { SagaState } from '#lib/api/types.gen.ts';
import { fieldTitle } from '#lib/formatters.ts';

test('the state filter offers every saga state the API knows', async ({ adminPage }) => {
    await adminPage.goto('/admin/sagas');
    await expect(adminPage.getByLabel(fieldTitle('state'), { exact: true }).locator('option')).toHaveText([
        'All',
        ...Object.values(SagaState),
    ]);
});

test('clear empties the search', async ({ adminPage }) => {
    await adminPage.goto('/admin/sagas');
    const search = adminPage.getByLabel(fieldTitle('search'), { exact: true });
    await search.fill('anything');
    await adminPage.getByRole('button', { name: 'Clear' }).click();
    await expect(search).toHaveValue('');
});

test('the saga of a new execution shows up', async ({ adminPage, execution }) => {
    await adminPage.goto('/admin/sagas');
    await adminPage.getByLabel(fieldTitle('execution_id'), { exact: true }).fill(execution.execution_id);
    // The worker starts the saga a moment after the API accepts the execution; the page polls every 5 seconds
    await expect(adminPage.getByRole('table', { name: 'Sagas' }).getByRole('row')).toHaveCount(2, { timeout: 15_000 });
    for (const key of ['saga_name', 'state', 'created_at']) {
        await expect(adminPage.getByRole('columnheader', { name: fieldTitle(key), exact: true })).toBeVisible();
    }
});

test('auto-refresh turns off and its rate changes', async ({ adminPage }) => {
    await adminPage.goto('/admin/sagas');
    const rate = adminPage.getByLabel('Refresh every');
    await rate.selectOption('10');
    await expect(rate).toHaveValue('10');
    await adminPage.getByRole('checkbox', { name: 'Auto-refresh' }).uncheck();
    await expect(rate).toBeHidden();
});
