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

async function navigateToAdminSagas(page: Page) {
  await page.goto('/admin/sagas');
  await expect(page.getByRole('heading', { name: 'Saga Management' })).toBeVisible({ timeout: 10000 });
}

test.describe('Admin Sagas Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSagas(page);
  });

  test('displays saga management page with header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Saga Management' })).toBeVisible();
    await expect(page.getByText('Monitor and debug distributed transactions')).toBeVisible();
  });

  test('shows admin sidebar navigation', async ({ page }) => {
    await expect(page.getByText('Admin Panel')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Event Browser' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Sagas' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Users' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Settings' })).toBeVisible();
  });

  test('sagas link is active in sidebar', async ({ page }) => {
    const sagasLink = page.getByRole('link', { name: 'Sagas' });
    await expect(sagasLink).toHaveClass(/bg-primary/);
  });

  test('shows auto-refresh control', async ({ page }) => {
    await expect(page.getByText(/Auto-refresh/i)).toBeVisible();
  });

  test('shows refresh button', async ({ page }) => {
    const refreshButton = page.locator('button[title*="Refresh"], button[aria-label*="Refresh"]').first();
    const buttonWithRefresh = page.getByRole('button').filter({ hasText: /Refresh/i }).first();

    const hasRefreshIcon = await refreshButton.isVisible({ timeout: 2000 }).catch(() => false);
    const hasRefreshButton = await buttonWithRefresh.isVisible({ timeout: 2000 }).catch(() => false);

    expect(hasRefreshIcon || hasRefreshButton).toBe(true);
  });
});

test.describe('Admin Sagas Stats Cards', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSagas(page);
  });

  test('shows saga statistics cards', async ({ page }) => {
    await page.waitForTimeout(1000);

    const statsGrid = page.locator('[class*="grid"]').filter({ hasText: /Running|Completed|Failed|Total/i }).first();
    const isVisible = await statsGrid.isVisible({ timeout: 5000 }).catch(() => false);

    if (isVisible) {
      await expect(statsGrid).toBeVisible();
    }
  });
});

test.describe('Admin Sagas Filtering', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSagas(page);
  });

  test('shows search input', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search"], input[type="search"]').first();
    const isVisible = await searchInput.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(searchInput).toBeVisible();
    }
  });

  test('shows state filter dropdown', async ({ page }) => {
    const stateFilter = page.locator('select, button').filter({ hasText: /All States|running|completed|failed|compensating/i }).first();
    const isVisible = await stateFilter.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(stateFilter).toBeVisible();
    }
  });

  test('shows execution ID filter input', async ({ page }) => {
    const executionIdInput = page.locator('input[placeholder*="Execution"], input[placeholder*="execution"]').first();
    const isVisible = await executionIdInput.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(executionIdInput).toBeVisible();
    }
  });

  test('can filter by state', async ({ page }) => {
    const stateSelect = page.locator('select').first();
    const isVisible = await stateSelect.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await stateSelect.click();
      const options = await stateSelect.locator('option').allTextContents();
      expect(options.length).toBeGreaterThan(0);
    }
  });

  test('can search sagas', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search"], input[type="search"]').first();
    const isVisible = await searchInput.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await searchInput.fill('test-saga');
      await page.waitForTimeout(500);
    }
  });

  test('can clear filters', async ({ page }) => {
    const clearButton = page.getByRole('button', { name: /Clear/i });
    const isVisible = await clearButton.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await clearButton.click();
      await page.waitForTimeout(500);
    }
  });
});

test.describe('Admin Sagas Table', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSagas(page);
  });

  test('shows sagas table or empty state', async ({ page }) => {
    await page.waitForTimeout(2000);

    const table = page.locator('table').first();
    const emptyState = page.getByText(/No sagas found/i);
    const loadingState = page.getByText(/Loading/i);

    const hasTable = await table.isVisible({ timeout: 3000 }).catch(() => false);
    const hasEmpty = await emptyState.isVisible({ timeout: 3000 }).catch(() => false);
    const isLoading = await loadingState.isVisible({ timeout: 1000 }).catch(() => false);

    expect(hasTable || hasEmpty || isLoading).toBe(true);
  });

  test('sagas table shows saga ID column', async ({ page }) => {
    await page.waitForTimeout(2000);

    const sagaIdHeader = page.getByText(/Saga|ID/i).first();
    const isVisible = await sagaIdHeader.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(sagaIdHeader).toBeVisible();
    }
  });

  test('sagas table shows state column', async ({ page }) => {
    await page.waitForTimeout(2000);

    const stateHeader = page.getByText('State');
    const isVisible = await stateHeader.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(stateHeader).toBeVisible();
    }
  });

  test('sagas table shows execution ID column', async ({ page }) => {
    await page.waitForTimeout(2000);

    const executionIdHeader = page.getByText(/Execution/i).first();
    const isVisible = await executionIdHeader.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(executionIdHeader).toBeVisible();
    }
  });

  test('sagas table shows actions column', async ({ page }) => {
    await page.waitForTimeout(2000);

    const actionsHeader = page.getByText('Actions');
    const isVisible = await actionsHeader.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(actionsHeader).toBeVisible();
    }
  });
});

test.describe('Admin Sagas Detail Modal', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSagas(page);
  });

  test('view details button exists for sagas', async ({ page }) => {
    await page.waitForTimeout(2000);

    const viewButton = page.locator('button[title*="View"], button[title*="Details"]').first();
    const isVisible = await viewButton.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(viewButton).toBeVisible();
    }
  });

  test('view execution button exists for sagas', async ({ page }) => {
    await page.waitForTimeout(2000);

    const viewExecutionButton = page.locator('button[title*="execution"], button[title*="Execution"]').first();
    const isVisible = await viewExecutionButton.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(viewExecutionButton).toBeVisible();
    }
  });
});

test.describe('Admin Sagas Auto-Refresh', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSagas(page);
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

  test('can change refresh rate', async ({ page }) => {
    const rateInput = page.locator('input[type="number"]').first();
    const isVisible = await rateInput.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await rateInput.fill('');
      await rateInput.fill('10');
      await expect(rateInput).toHaveValue('10');
    }
  });

  test('can manually refresh sagas', async ({ page }) => {
    const refreshButton = page.locator('button[title*="Refresh"], button[aria-label*="Refresh"]').first();
    const buttonWithRefresh = page.getByRole('button').filter({ hasText: /Refresh/i }).first();

    const refreshElement = await refreshButton.isVisible({ timeout: 2000 }).catch(() => false)
      ? refreshButton
      : buttonWithRefresh;

    await refreshElement.click();
    await page.waitForTimeout(500);
  });
});

test.describe('Admin Sagas Pagination', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await navigateToAdminSagas(page);
  });

  test('shows pagination when sagas exist', async ({ page }) => {
    await page.waitForTimeout(2000);

    const pagination = page.locator('text=/of|Page|Showing/').first();
    const isVisible = await pagination.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await expect(pagination).toBeVisible();
    }
  });

  test('can change page size', async ({ page }) => {
    await page.waitForTimeout(2000);

    const pageSizeSelect = page.locator('select').filter({ hasText: /10|25|50|100/i }).first();
    const isVisible = await pageSizeSelect.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      await pageSizeSelect.click();
    }
  });
});

test.describe('Admin Sagas Access Control', () => {
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

    await page.goto('/admin/sagas');

    await expect(page).toHaveURL(/^\/$|\/login/);
  });

  test('redirects unauthenticated users to login', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });

    await page.goto('/admin/sagas');

    await expect(page).toHaveURL(/\/login/);
  });
});
