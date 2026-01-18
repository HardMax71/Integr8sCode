import { test as base, expect, type Page, type BrowserContext } from '@playwright/test';
import { ADMIN_ROUTES, type AdminPath } from '../src/lib/admin/constants';

export const TEST_USERS = {
  user: { username: 'user', password: 'user123' },
  admin: { username: 'admin', password: 'admin123' },
} as const;

// Worker-scoped fixtures: authenticate ONCE per worker, reuse context for all tests
type WorkerFixtures = {
  userContext: BrowserContext;
  adminContext: BrowserContext;
};

type TestFixtures = {
  userPage: Page;
  adminPage: Page;
};

export const test = base.extend<TestFixtures, WorkerFixtures>({
  // Worker-scoped: one login per worker, shared across all tests in that worker
  userContext: [async ({ browser }, use) => {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();
    await page.goto('/login');
    await page.locator('#username').fill(TEST_USERS.user.username);
    await page.locator('#password').fill(TEST_USERS.user.password);
    await page.locator('button[type="submit"]').click();
    await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
    await page.close();
    await use(context);
    await context.close();
  }, { scope: 'worker' }],

  adminContext: [async ({ browser }, use) => {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();
    await page.goto('/login');
    await page.locator('#username').fill(TEST_USERS.admin.username);
    await page.locator('#password').fill(TEST_USERS.admin.password);
    await page.locator('button[type="submit"]').click();
    await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
    await page.close();
    await use(context);
    await context.close();
  }, { scope: 'worker' }],

  // Test-scoped: new page per test, but reuses authenticated context
  userPage: async ({ userContext }, use) => {
    const page = await userContext.newPage();
    await use(page);
    await page.close();
  },

  adminPage: async ({ adminContext }, use) => {
    const page = await adminContext.newPage();
    await use(page);
    await page.close();
  },
});

// Helper functions using the default page (for tests that don't need pre-auth)
export async function loginAsUser(page: Page): Promise<void> {
  await page.goto('/login');
  await page.locator('#username').fill(TEST_USERS.user.username);
  await page.locator('#password').fill(TEST_USERS.user.password);
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
}

export async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/login');
  await page.locator('#username').fill(TEST_USERS.admin.username);
  await page.locator('#password').fill(TEST_USERS.admin.password);
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
}

export async function clearSession(page: Page): Promise<void> {
  await page.context().clearCookies();
  const url = page.url();
  if (!url || url === 'about:blank') {
    return; // No storage to clear on about:blank
  }
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
}

export function getAdminRoute(path: AdminPath) {
  const route = ADMIN_ROUTES.find(r => r.path === path);
  if (!route) throw new Error(`Unknown admin path: ${path}`);
  return route;
}

export async function navigateToAdminPage(page: Page, path: AdminPath): Promise<void> {
  const route = getAdminRoute(path);
  await page.goto(path);
  await expect(page.getByRole('heading', { name: route.pageHeading })).toBeVisible();
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
  await expect(page).toHaveURL(/\/login/);
}

export async function expectRedirectToHome(page: Page): Promise<void> {
  await expect(page).toHaveURL('/');
}

export async function expectTableOrEmptyState(
  page: Page,
  emptyTextPattern: RegExp,
  timeout = 10000
): Promise<boolean> {
  const tableRow = page.locator('table tbody tr').first();
  const emptyState = page.getByText(emptyTextPattern).first();
  await expect(tableRow.or(emptyState).first()).toBeVisible({ timeout });
  return await tableRow.isVisible().catch(() => false);
}

export async function expectTableColumn(page: Page, columnName: string, emptyPattern: RegExp): Promise<void> {
  const hasTable = await expectTableOrEmptyState(page, emptyPattern);
  if (hasTable) {
    await expect(page.getByRole('columnheader', { name: columnName })).toBeVisible();
  }
}

export async function runExampleAndExecute(page: Page): Promise<void> {
  await page.getByRole('button', { name: /Example/i }).click();
  await expect(page.locator('.cm-content')).not.toBeEmpty({ timeout: 2000 });
  await page.getByRole('button', { name: /Run Script/i }).click();
  await expect(page.getByRole('button', { name: /Executing/i })).toBeVisible({ timeout: 5000 });
  const success = page.locator('text=Status:').first();
  const failure = page.getByText('Execution Failed');
  await expect(success.or(failure).first()).toBeVisible({ timeout: 10000 });
  await expect(success).toBeVisible({ timeout: 1000 });
}

export async function expectAuthRequired(page: Page, path: string): Promise<void> {
  await clearSession(page);
  await page.goto(path);
  await expectRedirectToLogin(page);
}

export async function navigateToPage(page: Page, path: string, headingName: string, headingLevel: 1 | 2 = 1): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole('heading', { name: headingName, level: headingLevel })).toBeVisible();
}

export function describeAuthRequired(testFn: typeof base, path: string): void {
  testFn.describe('Access Control', () => {
    testFn('redirects to login when not authenticated', async ({ page }) => {
      await expectAuthRequired(page, path);
    });
  });
}

export function describeAdminAccessControl(testFn: typeof base, path: AdminPath): void {
  testFn.describe('Access Control', () => {
    testFn('redirects non-admin users to home', async ({ userPage }) => {
      await userPage.goto(path);
      await expectRedirectToHome(userPage);
    });

    testFn('redirects unauthenticated users to login', async ({ page }) => {
      await clearSession(page);
      await page.goto(path);
      await expectRedirectToLogin(page);
    });
  });
}

export function describeAdminCommonTests(testFn: typeof base, path: AdminPath): void {
  const route = getAdminRoute(path);

  testFn('displays page with header', async ({ adminPage }) => {
    await adminPage.goto(path);
    await expect(adminPage.getByRole('heading', { name: route.pageHeading })).toBeVisible();
  });

  testFn('shows admin sidebar navigation', async ({ adminPage }) => {
    await adminPage.goto(path);
    await expectAdminSidebar(adminPage);
  });

  testFn('nav link is active in sidebar', async ({ adminPage }) => {
    await adminPage.goto(path);
    await expectActiveNavLink(adminPage, route.sidebarLabel);
  });
}

export { expect, ADMIN_ROUTES, type AdminPath, type Page };
