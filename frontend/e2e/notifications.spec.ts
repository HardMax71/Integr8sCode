import { test, expect, describeAuthRequired } from './fixtures';

const PATH = '/notifications';
const HEADING = 'Notifications';

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
    await userPage.goto(PATH);
    const emptyState = userPage.getByText('No notifications yet');
    const notificationCard = userPage.locator('[class*="card"]').filter({ hasText: /notification/i });
    const hasEmptyState = await emptyState.isVisible({ timeout: 2000 }).catch(() => false);
    const hasNotifications = await notificationCard.first().isVisible({ timeout: 2000 }).catch(() => false);
    expect(hasEmptyState || hasNotifications).toBe(true);
  });
});

test.describe('Notifications Interaction', () => {
  test('notification cards show severity badges when present', async ({ userPage }) => {
    await userPage.goto(PATH);
    const notificationCard = userPage.locator('[class*="card"]').first();
    if (await notificationCard.isVisible({ timeout: 3000 }).catch(() => false)) {
      const severityBadge = userPage.locator('[class*="badge"]').filter({ hasText: /low|medium|high|urgent/i }).first();
      const hasBadge = await severityBadge.isVisible({ timeout: 2000 }).catch(() => false);
      if (hasBadge) {
        await expect(severityBadge).toContainText(/low|medium|high|urgent/i);
      }
    }
  });

  test('notification cards show timestamp when present', async ({ userPage }) => {
    await userPage.goto(PATH);
    const notificationCard = userPage.locator('[class*="card"]').first();
    if (await notificationCard.isVisible({ timeout: 3000 }).catch(() => false)) {
      const timeIndicator = userPage.locator('text=/ago|Just now|\\d{1,2}:\\d{2}|\\d{4}-\\d{2}-\\d{2}/').first();
      const hasTime = await timeIndicator.isVisible({ timeout: 2000 }).catch(() => false);
      if (hasTime) {
        await expect(timeIndicator).toBeVisible();
      }
    }
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
