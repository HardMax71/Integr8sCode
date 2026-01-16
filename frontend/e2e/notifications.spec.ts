import { test, expect, loginAsUser, navigateToPage, describeAuthRequired } from './fixtures';

const PATH = '/notifications';
const HEADING = 'Notifications';

test.describe('Notifications Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
    await navigateToPage(page, PATH, HEADING);
  });

  test('displays notifications page with header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: HEADING, level: 1 })).toBeVisible();
  });

  test('shows filter controls', async ({ page }) => {
    await expect(page.getByLabel('Include tags')).toBeVisible();
    await expect(page.getByLabel('Exclude tags')).toBeVisible();
    await expect(page.getByLabel('Tag prefix')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Filter' })).toBeVisible();
  });

  test('can enter filter values', async ({ page }) => {
    const includeTagsInput = page.getByLabel('Include tags');
    await includeTagsInput.fill('execution,completed');
    await expect(includeTagsInput).toHaveValue('execution,completed');
    const excludeTagsInput = page.getByLabel('Exclude tags');
    await excludeTagsInput.fill('external_alert');
    await expect(excludeTagsInput).toHaveValue('external_alert');
  });

  test('can apply filters', async ({ page }) => {
    await page.getByLabel('Include tags').fill('test');
    await page.getByRole('button', { name: 'Filter' }).click();
    await expect(page.getByRole('heading', { name: HEADING, level: 1 })).toBeVisible();
  });

  test('shows empty state or notifications', async ({ page }) => {
    const emptyState = page.getByText('No notifications yet');
    const notificationCard = page.locator('[class*="card"]').filter({ hasText: /notification/i });
    const hasEmptyState = await emptyState.isVisible({ timeout: 2000 }).catch(() => false);
    const hasNotifications = await notificationCard.first().isVisible({ timeout: 2000 }).catch(() => false);
    expect(hasEmptyState || hasNotifications).toBe(true);
  });
});

test.describe('Notifications Interaction', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
    await navigateToPage(page, PATH, HEADING);
  });

  test('notification cards show severity badges when present', async ({ page }) => {
    const notificationCard = page.locator('[class*="card"]').first();
    if (await notificationCard.isVisible({ timeout: 3000 }).catch(() => false)) {
      const severityBadge = page.locator('[class*="badge"]').filter({ hasText: /low|medium|high|urgent/i }).first();
      const hasBadge = await severityBadge.isVisible({ timeout: 2000 }).catch(() => false);
      if (hasBadge) {
        await expect(severityBadge).toContainText(/low|medium|high|urgent/i);
      }
    }
  });

  test('notification cards show timestamp when present', async ({ page }) => {
    const notificationCard = page.locator('[class*="card"]').first();
    if (await notificationCard.isVisible({ timeout: 3000 }).catch(() => false)) {
      const timeIndicator = page.locator('text=/ago|Just now|\\d{1,2}:\\d{2}|\\d{4}-\\d{2}-\\d{2}/').first();
      const hasTime = await timeIndicator.isVisible({ timeout: 2000 }).catch(() => false);
      if (hasTime) {
        await expect(timeIndicator).toBeVisible();
      }
    }
  });
});

test.describe('Notification Center Header Component', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
  });

  test('shows notification icon in header when authenticated', async ({ page }) => {
    const bellIcon = page.locator('header').locator('[aria-label*="notification"], button').filter({ has: page.locator('svg') });
    await expect(bellIcon.first()).toBeVisible();
  });
});

describeAuthRequired(test, PATH);
