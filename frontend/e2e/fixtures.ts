import { test as base, expect, type Page } from '@playwright/test';

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

export async function navigateToAdminPage(
  page: Page,
  path: '/admin/events' | '/admin/sagas' | '/admin/users' | '/admin/settings',
  expectedHeading: string
): Promise<void> {
  await page.goto(path);
  await expect(page.getByRole('heading', { name: expectedHeading })).toBeVisible({ timeout: 10000 });
}

export function adminPageTest(
  path: '/admin/events' | '/admin/sagas' | '/admin/users' | '/admin/settings',
  expectedHeading: string
) {
  return base.extend<{ adminPage: Page }>({
    adminPage: async ({ page }, use) => {
      await loginAsAdmin(page);
      await navigateToAdminPage(page, path, expectedHeading);
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

export { base as test, expect };
