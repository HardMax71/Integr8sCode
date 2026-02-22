import { test, expect, describeAuthRequired, expectToastVisible } from './fixtures';

const PATH = '/notifications';
const HEADING = 'Notifications';

// Helper to navigate and wait for notifications API response
async function gotoAndWaitForNotifications(page: import('@playwright/test').Page) {
  const notificationsResponse = page.waitForResponse(
    response => response.url().includes('/api/v1/notifications') && response.status() === 200
  );
  await page.goto(PATH);
  await notificationsResponse;
}

test.describe('Notifications Page', () => {
  test('displays notifications page with header', async ({ userPage }) => {
    await userPage.goto(PATH);
    await expect(userPage.getByRole('heading', { name: HEADING, level: 1 })).toBeVisible();
  });

  test('shows filter controls', async ({ userPage }) => {
    await userPage.goto(PATH);
    await expect(userPage.getByLabel('Include tags')).toBeVisible();
    await expect(userPage.getByLabel('Exclude tags')).toBeVisible();
    await expect(userPage.getByLabel('Tag prefix')).toBeVisible();
    await expect(userPage.getByRole('button', { name: 'Filter' })).toBeVisible();
  });

  test('can enter filter values', async ({ userPage }) => {
    await userPage.goto(PATH);
    const includeTagsInput = userPage.getByLabel('Include tags');
    await includeTagsInput.fill('execution,completed');
    await expect(includeTagsInput).toHaveValue('execution,completed');
    const excludeTagsInput = userPage.getByLabel('Exclude tags');
    await excludeTagsInput.fill('external_alert');
    await expect(excludeTagsInput).toHaveValue('external_alert');
  });

  test('can apply filters', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByLabel('Include tags').fill('test');
    await userPage.getByRole('button', { name: 'Filter' }).click();
    await expect(userPage.getByRole('heading', { name: HEADING, level: 1 })).toBeVisible();
  });

  test('shows empty state or notifications', async ({ userPage }) => {
    await gotoAndWaitForNotifications(userPage);
    const emptyState = userPage.getByText('No notifications yet');
    // Notification cards have aria-label="Mark notification as read"
    const notificationCard = userPage.locator('[aria-label="Mark notification as read"]').first();
    await expect(emptyState.or(notificationCard)).toBeVisible({ timeout: 5000 });
  });
});

// The following tests require at least one notification to be present.
// They are skipped in clean environments where no notifications have been generated.
// To run these tests: execute a script first to generate a completion notification,
// then re-run this suite.
test.describe('Notifications Interaction', () => {
  test.skip('notification cards show severity badges when present', async ({ userPage }) => {
    await gotoAndWaitForNotifications(userPage);
    const notificationCard = userPage.locator('[aria-label="Mark notification as read"]').first();
    await expect(notificationCard).toBeVisible({ timeout: 5000 });
    const severityBadge = notificationCard.locator('span').filter({ hasText: /^(low|medium|high|urgent)$/i }).first();
    const hasBadge = await severityBadge.isVisible().catch(() => false);
    if (hasBadge) {
      await expect(severityBadge).toContainText(/low|medium|high|urgent/i);
    }
  });

  test.skip('notification cards show timestamp when present', async ({ userPage }) => {
    await gotoAndWaitForNotifications(userPage);
    const notificationCard = userPage.locator('[aria-label="Mark notification as read"]').first();
    await expect(notificationCard).toBeVisible({ timeout: 5000 });
    await expect(notificationCard.getByText(/ago|Just now|\d{1,2}:\d{2}|\d{4}-\d{2}-\d{2}/)).toBeVisible();
  });
});

test.describe('Notification Actions', () => {
  test.skip('can mark notification as read by clicking', async ({ userPage }) => {
    await gotoAndWaitForNotifications(userPage);
    const notificationCard = userPage.locator('[aria-label="Mark notification as read"]').first();
    await expect(notificationCard).toBeVisible({ timeout: 5000 });
    const hasBlue = await notificationCard.evaluate(el => el.classList.toString().includes('bg-blue'));
    await notificationCard.click();
    if (hasBlue) {
      await expect(notificationCard.getByText('Read')).toBeVisible({ timeout: 3000 });
    }
  });

  test.skip('can delete a notification', async ({ userPage }) => {
    await gotoAndWaitForNotifications(userPage);
    const notificationCard = userPage.locator('[aria-label="Mark notification as read"]').first();
    await expect(notificationCard).toBeVisible({ timeout: 5000 });
    const deleteBtn = notificationCard.locator('button').filter({ has: userPage.locator('svg') }).first();
    await expect(deleteBtn).toBeVisible();
    await deleteBtn.click();
    await expectToastVisible(userPage);
  });

  test.skip('can mark all as read', async ({ userPage }) => {
    await gotoAndWaitForNotifications(userPage);
    const markAllBtn = userPage.getByRole('button', { name: /mark all as read/i });
    await expect(markAllBtn).toBeVisible({ timeout: 5000 });
    await markAllBtn.click();
    await expectToastVisible(userPage);
  });
});

test.describe('Notification Center Header Component', () => {
  test('shows notification icon in header when authenticated', async ({ userPage }) => {
    await userPage.goto(PATH);
    const bellIcon = userPage.locator('header').locator('[aria-label*="notification"], button').filter({ has: userPage.locator('svg') });
    await expect(bellIcon.first()).toBeVisible();
  });
});

describeAuthRequired(test, PATH);
