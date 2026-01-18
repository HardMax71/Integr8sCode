import { test, expect, describeAdminCommonTests, describeAdminAccessControl, expectTableOrEmptyState, expectTableColumn } from './fixtures';

const PATH = '/admin/events' as const;
const EMPTY_PATTERN = /No events found/i;

test.describe('Admin Events', () => {
  describeAdminCommonTests(test, PATH);

  test('shows action buttons', async ({ adminPage }) => {
    await adminPage.goto(PATH);
    await expect(adminPage.getByRole('button', { name: /Filters/i })).toBeVisible();
    await expect(adminPage.getByRole('button', { name: /Export/i })).toBeVisible();
    await expect(adminPage.getByRole('button', { name: /Refresh/i })).toBeVisible();
  });

  test.describe('Filtering', () => {
    test('filter panel shows date range inputs', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await adminPage.getByRole('button', { name: /Filters/i }).click();
      await expect(adminPage.locator('input[type="datetime-local"], input[type="date"]').first()).toBeVisible();
    });
  });

  test.describe('Export', () => {
    test('can open export dropdown', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await adminPage.getByRole('button', { name: /Export/i }).click();
      await expect(adminPage.getByText('CSV')).toBeVisible();
      await expect(adminPage.getByText('JSON')).toBeVisible();
    });
  });

  test.describe('Table', () => {
    test('shows events table or empty state', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await expectTableOrEmptyState(adminPage, EMPTY_PATTERN);
    });

    test('shows Time column when data exists', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      await expectTableColumn(adminPage, 'Time', EMPTY_PATTERN);
    });
  });

  test.describe('Refresh', () => {
    test('can manually refresh events', async ({ adminPage }) => {
      await adminPage.goto(PATH);
      const [response] = await Promise.all([
        adminPage.waitForResponse(resp => resp.url().includes('/events') && resp.status() === 200),
        adminPage.getByRole('button', { name: /Refresh/i }).click(),
      ]);
      expect(response.ok()).toBe(true);
      await expect(adminPage.getByRole('heading', { name: 'Event Browser' })).toBeVisible();
    });
  });
});

describeAdminAccessControl(test, PATH);
