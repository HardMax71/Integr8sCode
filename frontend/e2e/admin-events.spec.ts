import { expect, test } from './fixtures';
import { ExportFormat } from '#lib/api/types.gen.ts';
import { fieldTitle } from '#lib/formatters.ts';

test('the event browser shows the filter, export and refresh buttons', async ({ adminPage }) => {
    await adminPage.goto('/admin/events');
    for (const action of ['Filters', 'Export', 'Refresh']) {
        await expect(adminPage.getByRole('button', { name: action })).toBeVisible();
    }
});

test('the filter panel has the time range inputs', async ({ adminPage }) => {
    await adminPage.goto('/admin/events');
    await adminPage.getByRole('button', { name: 'Filters' }).click();
    await expect(adminPage.getByLabel(fieldTitle('start_time'))).toBeVisible();
    await expect(adminPage.getByLabel(fieldTitle('end_time'))).toBeVisible();
});

test('the export menu offers every export format', async ({ adminPage }) => {
    await adminPage.goto('/admin/events');
    await adminPage.getByRole('button', { name: 'Export' }).click();
    for (const format of Object.values(ExportFormat)) {
        await expect(adminPage.getByRole('menuitem', { name: `Export as ${format}` })).toBeVisible();
    }
});

test("a user's events show in the table and open their details", async ({ adminPage, account }) => {
    await adminPage.goto('/admin/events');
    await adminPage.getByRole('button', { name: 'Filters' }).click();
    await adminPage.getByLabel(fieldTitle('user_id')).fill(account.user_id);
    await adminPage.getByRole('button', { name: 'Apply' }).click();
    const table = adminPage.getByRole('table', { name: 'Events' });
    for (const key of ['timestamp', 'event_type', 'user_id']) {
        await expect(table.getByRole('columnheader', { name: fieldTitle(key), exact: true })).toBeVisible();
    }
    await table
        .getByRole('button', { name: /^View details for event / })
        .first()
        .click();
    const dialog = adminPage.getByRole('dialog', { name: 'Event Details' });
    await expect(dialog).toContainText(`"user_id": "${account.user_id}"`);
});

test('refresh fetches the events again', async ({ adminPage }) => {
    await adminPage.goto('/admin/events');
    await expect(adminPage.getByRole('table', { name: 'Events' })).toBeVisible();
    const refreshed = adminPage.waitForResponse('**/api/v1/admin/events/browse');
    await adminPage.getByRole('button', { name: 'Refresh' }).click();
    expect((await refreshed).ok()).toBe(true);
});
