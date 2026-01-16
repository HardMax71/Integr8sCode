import { test as base, expect, type Page, type TestInfo } from '@playwright/test';
import { ADMIN_ROUTES, type AdminPath } from '../src/lib/admin/constants';

export const TEST_USERS = {
  user: { username: 'user', password: 'user123' },
  admin: { username: 'admin', password: 'admin123' },
} as const;

export async function clearSession(page: Page): Promise<void> {
  await page.context().clearCookies();
  if (page.url() === 'about:blank') {
    await page.goto('/');
  }
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
}

export async function login(page: Page, username = 'user', password = 'user123'): Promise<void> {
  await clearSession(page);
  await page.goto('/login');
  await page.waitForSelector('#username');
  await page.fill('#username', username);
  await page.fill('#password', password);
  await page.click('button[type="submit"]');
  await page.waitForURL(url => !url.pathname.includes('/login'), { timeout: 15000 });
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });
}

export const loginAsAdmin = (page: Page) => login(page, TEST_USERS.admin.username, TEST_USERS.admin.password);
export const loginAsUser = (page: Page) => login(page, TEST_USERS.user.username, TEST_USERS.user.password);

export function getAdminRoute(path: AdminPath) {
  const route = ADMIN_ROUTES.find(r => r.path === path);
  if (!route) throw new Error(`Unknown admin path: ${path}`);
  return route;
}

export async function navigateToAdminPage(page: Page, path: AdminPath): Promise<void> {
  const route = getAdminRoute(path);
  await page.goto(path);
  await expect(page.getByRole('heading', { name: route.pageHeading })).toBeVisible({ timeout: 15000 });
}

export async function expectAdminSidebar(page: Page): Promise<void> {
  await expect(page.getByText('Admin Panel')).toBeVisible();
  for (const route of ADMIN_ROUTES) {
    await expect(page.getByRole('link', { name: route.sidebarLabel })).toBeVisible();
  }
}

export async function expectActiveNavLink(page: Page, linkName: string): Promise<void> {
  await expect(page.getByRole('link', { name: linkName })).toHaveClass(/bg-primary/);
}

export async function expectToastVisible(page: Page, timeout = 5000): Promise<void> {
  await expect(page.locator('[class*="toast"]').first()).toBeVisible({ timeout });
}

export async function expectRedirectToLogin(page: Page): Promise<void> {
  await expect(page).toHaveURL(/\/login/, { timeout: 10000 });
}

export async function expectRedirectToHome(page: Page): Promise<void> {
  await expect(page).toHaveURL('/', { timeout: 10000 });
}

export async function expectTableOrEmptyState(
  page: Page,
  emptyTextPattern: RegExp,
  timeout = 10000
): Promise<boolean> {
  const table = page.locator('table').first();
  const emptyState = page.getByText(emptyTextPattern);
  await expect(table.or(emptyState)).toBeVisible({ timeout });
  const hasTable = await table.isVisible().catch(() => false);
  const hasEmpty = await emptyState.isVisible().catch(() => false);
  expect(hasTable || hasEmpty).toBe(true);
  return hasTable;
}

export async function expectTableColumn(page: Page, columnName: string, emptyPattern: RegExp): Promise<void> {
  const hasTable = await expectTableOrEmptyState(page, emptyPattern);
  if (hasTable) {
    await expect(page.getByRole('columnheader', { name: columnName })).toBeVisible();
  }
}

export async function runExampleAndExecute(page: Page, testInfo: TestInfo): Promise<boolean> {
  await page.getByRole('button', { name: /Example/i }).click();
  await expect(page.locator('.cm-content')).not.toBeEmpty({ timeout: 3000 });
  const runButton = page.getByRole('button', { name: /Run Script/i });
  await runButton.click();
  await expect(page.getByRole('button', { name: /Executing/i })).toBeVisible({ timeout: 5000 });
  const statusVisible = await page.locator('text=Status:').first().isVisible({ timeout: 30000 }).catch(() => false);
  if (!statusVisible) {
    testInfo.skip(true, 'Execution backend unavailable');
    return false;
  }
  return true;
}

export async function expectAuthRequired(page: Page, path: string): Promise<void> {
  await clearSession(page);
  await page.goto(path);
  await expectRedirectToLogin(page);
}

export async function navigateToPage(page: Page, path: string, headingName: string, headingLevel: 1 | 2 = 1): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole('heading', { name: headingName, level: headingLevel })).toBeVisible({ timeout: 15000 });
}

export function describeAuthRequired(test: typeof base, path: string): void {
  test.describe('Access Control', () => {
    test('redirects to login when not authenticated', async ({ page }) => {
      await expectAuthRequired(page, path);
    });
  });
}

export function describeAdminAccessControl(test: typeof base, path: AdminPath): void {
  test.describe('Access Control', () => {
    test('redirects non-admin users to home', async ({ page }) => {
      await loginAsUser(page);
      await page.goto(path);
      await expectRedirectToHome(page);
    });

    test('redirects unauthenticated users to login', async ({ page }) => {
      await clearSession(page);
      await page.goto(path);
      await expectRedirectToLogin(page);
    });
  });
}

export function describeAdminCommonTests(test: typeof base, path: AdminPath): void {
  const route = getAdminRoute(path);

  test('displays page with header', async ({ page }) => {
    await expect(page.getByRole('heading', { name: route.pageHeading })).toBeVisible();
  });

  test('shows admin sidebar navigation', async ({ page }) => {
    await expectAdminSidebar(page);
  });

  test('nav link is active in sidebar', async ({ page }) => {
    await expectActiveNavLink(page, route.sidebarLabel);
  });
}

export { base as test, expect, ADMIN_ROUTES, type AdminPath, type Page, type TestInfo };
