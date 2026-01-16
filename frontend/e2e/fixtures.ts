import { test as base, expect, type Page } from '@playwright/test';
import { ADMIN_ROUTES, type AdminPath } from '../src/lib/admin/constants';

export const TEST_USERS = {
  user: { username: 'user', password: 'user123' },
  admin: { username: 'admin', password: 'admin123' },
} as const;

export async function clearSession(page: Page): Promise<void> {
  await page.context().clearCookies();
  // Navigate to app first if on about:blank, then clear storage
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
  // Wait for navigation away from login page first
  await page.waitForURL(url => !url.pathname.includes('/login'), { timeout: 15000 });
  // Then verify we're on the editor page
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });
}

export async function loginAsAdmin(page: Page): Promise<void> {
  await login(page, TEST_USERS.admin.username, TEST_USERS.admin.password);
}

export async function loginAsUser(page: Page): Promise<void> {
  await login(page, TEST_USERS.user.username, TEST_USERS.user.password);
}

export async function isVisibleWithTimeout(page: Page, selector: string, timeout = 3000): Promise<boolean> {
  try {
    await page.locator(selector).first().waitFor({ state: 'visible', timeout });
    return true;
  } catch {
    return false;
  }
}

export function getAdminRoute(path: AdminPath) {
  const route = ADMIN_ROUTES.find(r => r.path === path);
  if (!route) throw new Error(`Unknown admin path: ${path}`);
  return route;
}

export async function navigateToAdminPage(page: Page, path: AdminPath): Promise<void> {
  const route = getAdminRoute(path);
  await page.goto(path);
  // Wait for network to be idle before checking heading
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
  await expect(page.getByRole('heading', { name: route.pageHeading })).toBeVisible({ timeout: 15000 });
}

export function adminPageTest(path: AdminPath) {
  return base.extend<{ adminPage: Page }>({
    adminPage: async ({ page }, use) => {
      await loginAsAdmin(page);
      await navigateToAdminPage(page, path);
      await use(page);
    },
  });
}

export function userPageTest(targetPath: string, expectedSelector: string) {
  return base.extend<{ userPage: Page }>({
    userPage: async ({ page }, use) => {
      await loginAsUser(page);
      await page.goto(targetPath);
      await expect(page.locator(expectedSelector)).toBeVisible({ timeout: 10000 });
      await use(page);
    },
  });
}

export async function expectAdminSidebar(page: Page): Promise<void> {
  await expect(page.getByText('Admin Panel')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Event Browser' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Sagas' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Users' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Settings' })).toBeVisible();
}

export async function expectToastVisible(page: Page, timeout = 5000): Promise<boolean> {
  try {
    await page.locator('[class*="toast"]').first().waitFor({ state: 'visible', timeout });
    return true;
  } catch {
    return false;
  }
}

export async function testAccessControl(
  page: Page,
  targetPath: string,
  expectedRedirectPattern: RegExp
): Promise<void> {
  await clearSession(page);
  await page.goto('/login');
  await page.goto(targetPath);
  await expect(page).toHaveURL(expectedRedirectPattern);
}

export async function testNonAdminAccessControl(page: Page, targetPath: string): Promise<void> {
  await loginAsUser(page);
  await page.goto(targetPath);
  await expect(page).toHaveURL(/^\/$|\/login/);
}

export async function testAdminAccessControl(
  page: Page,
  path: AdminPath,
  options: { testUnauthenticated?: boolean; testNonAdmin?: boolean } = { testUnauthenticated: true, testNonAdmin: true }
): Promise<void> {
  if (options.testUnauthenticated) {
    await clearSession(page);
    await page.goto(path);
    await expect(page).toHaveURL(/\/login/);
  }

  if (options.testNonAdmin) {
    await loginAsUser(page);
    await page.goto(path);
    await page.waitForURL(url => url.pathname === '/' || url.pathname.includes('/login'));
  }
}

export { base as test, expect, ADMIN_ROUTES, type AdminPath };
