import { test as setup, expect } from '@playwright/test';
import { TEST_USERS } from './fixtures';

const USER_AUTH_FILE = 'e2e/.auth/user.json';
const ADMIN_AUTH_FILE = 'e2e/.auth/admin.json';

setup('authenticate as user', async ({ page }) => {
  await page.goto('/login');
  await page.locator('#username').fill(TEST_USERS.user.username);
  await page.locator('#password').fill(TEST_USERS.user.password);
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });
  await page.context().storageState({ path: USER_AUTH_FILE });
});

setup('authenticate as admin', async ({ page }) => {
  await page.goto('/login');
  await page.locator('#username').fill(TEST_USERS.admin.username);
  await page.locator('#password').fill(TEST_USERS.admin.password);
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });
  await page.context().storageState({ path: ADMIN_AUTH_FILE });
});
