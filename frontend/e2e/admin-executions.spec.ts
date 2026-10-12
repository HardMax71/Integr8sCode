import { test, expect, describeAdminCommonTests, describeAdminAccessControl, expectTableOrEmptyState, expectTableColumn } from './fixtures';

const PATH = '/admin/executions' as const;
const EMPTY_PATTERN = /No executions found/i;

test.describe('Admin Executions', () => {
  describeAdminCommonTests(test, PATH);

  test('shows refresh button', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await expect(adminPage.getByRole('button', { name: /Refresh/i })).toBeVisible();
  });

  test('shows filter controls', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await expect(adminPage.getByLabel('Status', { exact: true })).toBeVisible();
    await expect(adminPage.getByLabel('Priority', { exact: true })).toBeVisible();
    await expect(adminPage.getByLabel('User Id', { exact: true })).toBeVisible();
  });

  test.describe('Filters', () => {
    test('status filter dropdown has expected options', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      const statusSelect = adminPage.getByLabel('Status', { exact: true });
      await expect(statusSelect).toBeVisible();
      await expect(statusSelect.locator('option')).toHaveCount(9); // All + 8 statuses
    });

    test('priority filter dropdown has expected options', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      const prioritySelect = adminPage.getByLabel('Priority', { exact: true });
      await expect(prioritySelect).toBeVisible();
      await expect(prioritySelect.locator('option')).toHaveCount(6); // All + 5 priorities
    });
  });

  test.describe('Table', () => {
    test('shows executions table or empty state', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await expectTableOrEmptyState(adminPage, EMPTY_PATTERN);
    });

    test('shows Execution Id column when data exists', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await expectTableColumn(adminPage, 'Execution Id', EMPTY_PATTERN);
    });
  });

  test.describe('Refresh', () => {
    test('can manually refresh executions', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      const [response] = await Promise.all([
        adminPage.waitForResponse(resp => resp.url().includes('/api/v1/admin/executions') && resp.status() === 200),
        adminPage.getByRole('button', { name: /Refresh/i }).click(),
      ]);
      expect(response.ok()).toBe(true);
      await expect(adminPage.getByRole('heading', { name: 'Execution Management' })).toBeVisible();
    });
  });
});

describeAdminAccessControl(test, PATH);
