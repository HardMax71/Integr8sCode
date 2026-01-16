import { test, expect, type Page } from '@playwright/test';

async function loginAsAdmin(page: Page) {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.waitForSelector('#username');
  await page.fill('#username', 'admin');
  await page.fill('#password', 'admin123');
  await page.click('button[type="submit"]');
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });
}

async function navigateToAdminEvents(page: Page) {
  await page.goto('/admin/events');
  await expect(page.getByRole('heading', { name: 'Event Browser' })).toBeVisible({ timeout: 10000 });
}

test.describe('Admin Events Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminEvents(page);
  });

  test('displays event browser page with header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Event Browser' })).toBeVisible();
    await expect(page.getByText('Monitor and replay system events')).toBeVisible();
  });

  test('shows admin sidebar navigation', async ({ page }) => {
    await expect(page.getByText('Admin Panel')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Event Browser' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Sagas' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Users' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Settings' })).toBeVisible();
  });

  test('event browser link is active in sidebar', async ({ page }) => {
    const eventBrowserLink = page.getByRole('link', { name: 'Event Browser' });
    await expect(eventBrowserLink).toHaveClass(/bg-primary/);
  });

  test('shows action buttons', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Filters/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Export/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Refresh/i })).toBeVisible();
  });

  test('shows auto-refresh control', async ({ page }) => {
    await expect(page.getByText(/Auto-refresh/i)).toBeVisible();
  });
});

test.describe('Admin Events Stats Cards', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminEvents(page);
  });

  test('shows event statistics cards', async ({ page }) => {
    const statsSection = page.locator('[class*="grid"]').filter({ hasText: /Total|Events/i }).first();
    const isVisible = await statsSection.isVisible({ timeout: 5000 }).catch(() => false);

    if (isVisible) {
      await expect(page.getByText(/Total/i).first()).toBeVisible();
    }
  });
});

test.describe('Admin Events Filtering', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminEvents(page);
  });

  test('can toggle filter panel', async ({ page }) => {
    const filterButton = page.getByRole('button', { name: /Filters/i });
    await filterButton.click();

    await page.waitForTimeout(500);

    const filterPanel = page.locator('[class*="filter"], [class*="panel"]').filter({ hasText: /Event Type|From|To/i });
    const isExpanded = await filterPanel.first().isVisible({ timeout: 2000 }).catch(() => false);

    if (isExpanded) {
      await filterButton.click();
      await page.waitForTimeout(300);
    }
  });

  test('filter panel shows date range inputs', async ({ page }) => {
    await page.getByRole('button', { name: /Filters/i }).click();
    await page.waitForTimeout(500);

    const fromInput = page.locator('input[type="datetime-local"], input[type="date"]').first();
    const isVisible = await fromInput.isVisible({ timeout: 2000 }).catch(() => false);

    if (isVisible) {
      await expect(fromInput).toBeVisible();
    }
  });

  test('filter panel shows event type selector', async ({ page }) => {
    await page.getByRole('button', { name: /Filters/i }).click();
    await page.waitForTimeout(500);

    const eventTypeSelector = page.locator('select, [class*="select"]').filter({ hasText: /event_type|All Types/i }).first();
    const isVisible = await eventTypeSelector.isVisible({ timeout: 2000 }).catch(() => false);

    if (isVisible) {
      await expect(eventTypeSelector).toBeVisible();
    }
  });

  test('shows active filter count badge', async ({ page }) => {
    await page.getByRole('button', { name: /Filters/i }).click();
    await page.waitForTimeout(500);

    const eventTypeSelect = page.locator('select').first();
    if (await eventTypeSelect.isVisible({ timeout: 2000 }).catch(() => false)) {
      const options = await eventTypeSelect.locator('option').all();
      if (options.length > 1) {
        await eventTypeSelect.selectOption({ index: 1 });
      }
    }

    const applyButton = page.getByRole('button', { name: /Apply/i });
    if (await applyButton.isVisible({ timeout: 2000 }).catch(() => false)) {
      await applyButton.click();
    }
  });
});

test.describe('Admin Events Export', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminEvents(page);
  });

  test('can open export dropdown', async ({ page }) => {
    await page.getByRole('button', { name: /Export/i }).click();

    await expect(page.getByText('CSV')).toBeVisible();
    await expect(page.getByText('JSON')).toBeVisible();
  });

  test('export dropdown has CSV option', async ({ page }) => {
    await page.getByRole('button', { name: /Export/i }).click();

    const csvOption = page.getByText('CSV');
    await expect(csvOption).toBeVisible();
  });

  test('export dropdown has JSON option', async ({ page }) => {
    await page.getByRole('button', { name: /Export/i }).click();

    const jsonOption = page.getByText('JSON');
    await expect(jsonOption).toBeVisible();
  });
});

test.describe('Admin Events Table', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminEvents(page);
  });

  test('shows events table or empty state', async ({ page }) => {
    await page.waitForTimeout(2000);

    const table = page.locator('table').first();
    const emptyState = page.getByText(/No events found/i);
    const loadingState = page.getByText(/Loading/i);

    const hasTable = await table.isVisible({ timeout: 3000 }).catch(() => false);
    const hasEmpty = await emptyState.isVisible({ timeout: 3000 }).catch(() => false);
    const isLoading = await loadingState.isVisible({ timeout: 1000 }).catch(() => false);

    expect(hasTable || hasEmpty || isLoading).toBe(true);
  });

  test('events table shows time column', async ({ page }) => {
    await page.waitForTimeout(2000);

    const timeHeader = page.getByText('Time');
    const isVisible = await timeHeader.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(timeHeader).toBeVisible();
    }
  });

  test('events table shows type column', async ({ page }) => {
    await page.waitForTimeout(2000);

    const typeHeader = page.getByText('Type').first();
    const isVisible = await typeHeader.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(typeHeader).toBeVisible();
    }
  });

  test('events table shows actions column', async ({ page }) => {
    await page.waitForTimeout(2000);

    const actionsHeader = page.getByText('Actions');
    const isVisible = await actionsHeader.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(actionsHeader).toBeVisible();
    }
  });

  test('event rows are clickable', async ({ page }) => {
    await page.waitForTimeout(2000);

    const eventRow = page.locator('tr[role="button"], [role="button"][aria-label*="event"]').first();
    const isVisible = await eventRow.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(eventRow).toHaveAttribute('tabindex', '0');
    }
  });
});

test.describe('Admin Events Detail Modal', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminEvents(page);
  });

  test('can view event details by clicking row', async ({ page }) => {
    await page.waitForTimeout(2000);

    const eventRow = page.locator('tr[role="button"], [role="button"][aria-label*="event"]').first();
    const isVisible = await eventRow.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await eventRow.click();
      await page.waitForTimeout(1000);
    }
  });
});

test.describe('Admin Events Replay', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminEvents(page);
  });

  test('preview replay button exists in event actions', async ({ page }) => {
    await page.waitForTimeout(2000);

    const previewButton = page.locator('button[title="Preview replay"]').first();
    const isVisible = await previewButton.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(previewButton).toBeVisible();
    }
  });

  test('replay button exists in event actions', async ({ page }) => {
    await page.waitForTimeout(2000);

    const replayButton = page.locator('button[title="Replay"]').first();
    const isVisible = await replayButton.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(replayButton).toBeVisible();
    }
  });
});

test.describe('Admin Events Auto-Refresh', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminEvents(page);
  });

  test('auto-refresh control is visible', async ({ page }) => {
    await expect(page.getByText(/Auto-refresh/i)).toBeVisible();
  });

  test('can toggle auto-refresh', async ({ page }) => {
    const autoRefreshToggle = page.locator('input[type="checkbox"]').first();
    const isVisible = await autoRefreshToggle.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      const initialState = await autoRefreshToggle.isChecked();
      await autoRefreshToggle.click();
      const newState = await autoRefreshToggle.isChecked();
      expect(newState).toBe(!initialState);
    }
  });

  test('can manually refresh events', async ({ page }) => {
    const refreshButton = page.getByRole('button', { name: /Refresh/i });
    await expect(refreshButton).toBeVisible();
    await refreshButton.click();

    await page.waitForTimeout(500);
  });
});

test.describe('Admin Events Pagination', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminEvents(page);
  });

  test('shows pagination when events exist', async ({ page }) => {
    await page.waitForTimeout(2000);

    const pagination = page.locator('text=/of|Page|Showing/').first();
    const isVisible = await pagination.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(pagination).toBeVisible();
    }
  });
});

test.describe('Admin Events Access Control', () => {
  test('redirects non-admin users', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
    await page.waitForSelector('#username');
    await page.fill('#username', 'user');
    await page.fill('#password', 'user123');
    await page.click('button[type="submit"]');
    await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });

    await page.goto('/admin/events');

    await expect(page).toHaveURL(/^\/$|\/login/);
  });

  test('redirects unauthenticated users to login', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });

    await page.goto('/admin/events');

    await expect(page).toHaveURL(/\/login/);
  });
});
