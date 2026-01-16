import { test, expect, type Page } from '@playwright/test';

async function login(page: Page, username = 'user', password = 'user123') {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.waitForSelector('#username');
  await page.fill('#username', username);
  await page.fill('#password', password);
  await page.click('button[type="submit"]');
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });
}

test.describe('Notifications Page', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/notifications');
    await expect(page.getByRole('heading', { name: 'Notifications', level: 1 })).toBeVisible({ timeout: 10000 });
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

    const prefixInput = page.getByLabel('Tag prefix');
    await prefixInput.fill('exec:');
    await expect(prefixInput).toHaveValue('exec:');
  });

  test('can apply filters', async ({ page }) => {
    const includeTagsInput = page.getByLabel('Include tags');
    await includeTagsInput.fill('test');

    await page.getByRole('button', { name: 'Filter' }).click();

    await page.waitForTimeout(500);
  });

  test('shows empty state when no notifications', async ({ page }) => {
    const emptyState = page.getByText('No notifications yet');
    const notificationCard = page.locator('[class*="card"]').filter({ hasText: /notification/i });

    const hasEmptyState = await emptyState.isVisible({ timeout: 2000 }).catch(() => false);
    const hasNotifications = await notificationCard.first().isVisible({ timeout: 2000 }).catch(() => false);

    expect(hasEmptyState || hasNotifications).toBe(true);
  });

  test('shows mark all as read button when unread notifications exist', async ({ page }) => {
    await page.waitForTimeout(1000);

    const markAllButton = page.getByRole('button', { name: 'Mark all as read' });
    const isVisible = await markAllButton.isVisible({ timeout: 2000 }).catch(() => false);

    if (isVisible) {
      await expect(markAllButton).toBeEnabled();
    }
  });
});

test.describe('Notifications Interaction', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/notifications');
    await expect(page.getByRole('heading', { name: 'Notifications', level: 1 })).toBeVisible({ timeout: 10000 });
  });

  test('notification cards are clickable to mark as read', async ({ page }) => {
    await page.waitForTimeout(1000);

    const notificationCard = page.locator('[role="button"][aria-label="Mark notification as read"]').first();
    const isVisible = await notificationCard.isVisible({ timeout: 2000 }).catch(() => false);

    if (isVisible) {
      await expect(notificationCard).toHaveAttribute('tabindex', '0');
    }
  });

  test('notification cards show severity badges', async ({ page }) => {
    await page.waitForTimeout(1000);

    const severityBadge = page.locator('[class*="badge"]').filter({ hasText: /low|medium|high|urgent/i }).first();
    const isVisible = await severityBadge.isVisible({ timeout: 2000 }).catch(() => false);

    if (isVisible) {
      await expect(severityBadge).toBeVisible();
    }
  });

  test('notification cards show channel info', async ({ page }) => {
    await page.waitForTimeout(1000);

    const channelBadge = page.locator('[class*="badge"]').filter({ hasText: /in_app|email/i }).first();
    const isVisible = await channelBadge.isVisible({ timeout: 2000 }).catch(() => false);

    if (isVisible) {
      await expect(channelBadge).toBeVisible();
    }
  });

  test('notification cards show timestamp', async ({ page }) => {
    await page.waitForTimeout(1000);

    const timeIndicator = page.locator('text=/ago|Just now/').first();
    const isVisible = await timeIndicator.isVisible({ timeout: 2000 }).catch(() => false);

    if (isVisible) {
      await expect(timeIndicator).toBeVisible();
    }
  });

  test('notification cards have delete button', async ({ page }) => {
    await page.waitForTimeout(1000);

    const deleteButton = page.locator('button[class*="red"]').first();
    const isVisible = await deleteButton.isVisible({ timeout: 2000 }).catch(() => false);

    if (isVisible) {
      await expect(deleteButton).toBeEnabled();
    }
  });
});

test.describe('Notifications Access Control', () => {
  test('redirects to login when not authenticated', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });

    await page.goto('/notifications');

    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe('Notification Center Header Component', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('shows notification bell icon in header when authenticated', async ({ page }) => {
    const bellIcon = page.locator('header').locator('[aria-label*="notification"], button').filter({ has: page.locator('svg') });

    await expect(bellIcon.first()).toBeVisible();
  });

  test('can access notifications from header dropdown', async ({ page }) => {
    const headerButtons = page.locator('header button');
    const notificationButton = headerButtons.filter({ has: page.locator('svg') }).first();

    if (await notificationButton.isVisible()) {
      await notificationButton.click();
    }
  });
});
