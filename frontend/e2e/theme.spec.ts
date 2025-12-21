import { test, expect } from '@playwright/test';

test.describe('Theme', () => {
  test.beforeEach(async ({ page }) => {
    // Clear theme storage before each test
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.removeItem('app-theme');
    });
  });

  test('auto theme follows system light preference', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto('/login');
    await page.waitForLoadState('networkidle');

    const hasDarkClass = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    );
    expect(hasDarkClass).toBe(false);
  });

  test('auto theme follows system dark preference', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto('/login');
    await page.waitForLoadState('networkidle');

    const hasDarkClass = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    );
    expect(hasDarkClass).toBe(true);
  });

  test('explicit dark theme overrides system preference', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto('/login');
    await page.evaluate(() => localStorage.setItem('app-theme', 'dark'));
    await page.reload();
    await page.waitForLoadState('networkidle');

    const hasDarkClass = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    );
    expect(hasDarkClass).toBe(true);
  });

  test('explicit light theme overrides system preference', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto('/login');
    await page.evaluate(() => localStorage.setItem('app-theme', 'light'));
    await page.reload();
    await page.waitForLoadState('networkidle');

    const hasDarkClass = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    );
    expect(hasDarkClass).toBe(false);
  });

  test('theme persists across page navigation', async ({ page }) => {
    await page.goto('/login');
    await page.evaluate(() => localStorage.setItem('app-theme', 'dark'));
    await page.goto('/register');
    await page.waitForLoadState('networkidle');

    const storedTheme = await page.evaluate(() => localStorage.getItem('app-theme'));
    expect(storedTheme).toBe('dark');

    const hasDarkClass = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    );
    expect(hasDarkClass).toBe(true);
  });
});
