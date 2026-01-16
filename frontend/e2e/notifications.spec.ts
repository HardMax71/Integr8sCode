import { test, expect, loginAsUser, clearSession } from './fixtures';

const navigateToNotifications = async (page: import('@playwright/test').Page) => {
  await page.goto('/notifications');
  await expect(page.getByRole('heading', { name: 'Notifications', level: 1 })).toBeVisible({ timeout: 10000 });
};

test.describe('Notifications Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
    await navigateToNotifications(page);
  });

  test('displays notifications page with header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Notifications', level: 1 })).toBeVisible();
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
    // Verify page still functional after applying filters
    await expect(page.getByRole('heading', { name: 'Notifications' })).toBeVisible();
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
    await navigateToNotifications(page);
  });

  test('notification cards show severity badges when present', async ({ page }) => {
    const notificationCard = page.locator('[class*="card"]').first();
    // Only verify badge content if notifications exist
    if (await notificationCard.isVisible({ timeout: 3000 }).catch(() => false)) {
      // When notification cards exist, they should contain severity badges
      const severityBadge = notificationCard.locator('[class*="badge"]').filter({ hasText: /low|medium|high|urgent/i });
      await expect(severityBadge).toBeVisible();
    }
  });

  test('notification cards show timestamp when present', async ({ page }) => {
    const notificationCard = page.locator('[class*="card"]').first();
    // Only verify timestamp content if notifications exist
    if (await notificationCard.isVisible({ timeout: 3000 }).catch(() => false)) {
      // When notification cards exist, they should contain timestamps
      const timeIndicator = notificationCard.locator('text=/ago|Just now/');
      await expect(timeIndicator).toBeVisible();
    }
  });
});

test.describe('Notifications Access Control', () => {
  test('redirects to login when not authenticated', async ({ page }) => {
    await clearSession(page);
    await page.goto('/notifications');
    await expect(page).toHaveURL(/\/login/);
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
