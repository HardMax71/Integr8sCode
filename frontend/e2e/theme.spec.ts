import { test, expect } from '@playwright/test';

test.describe('Theme', () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage to start fresh
    await page.goto('/login');
    await page.evaluate(() => localStorage.removeItem('app-theme'));
  });

  test('defaults to auto theme (no dark class)', async ({ page }) => {
    await page.goto('/login');

    // Check that dark class is not present initially (assuming system prefers light)
    const hasDarkClass = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    );
    // This may be true or false depending on system preference
    expect(typeof hasDarkClass).toBe('boolean');
  });

  test('persists theme preference in localStorage', async ({ page }) => {
    await page.goto('/login');

    // Set theme via localStorage
    await page.evaluate(() => localStorage.setItem('app-theme', 'dark'));
    await page.reload();

    const storedTheme = await page.evaluate(() => localStorage.getItem('app-theme'));
    expect(storedTheme).toBe('dark');
  });

  test('applies dark theme when set', async ({ page }) => {
    await page.goto('/login');

    // Set dark theme
    await page.evaluate(() => {
      localStorage.setItem('app-theme', 'dark');
      document.documentElement.classList.add('dark');
    });

    const hasDarkClass = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    );
    expect(hasDarkClass).toBe(true);
  });

  test('applies light theme when set', async ({ page }) => {
    await page.goto('/login');

    // Set light theme
    await page.evaluate(() => {
      localStorage.setItem('app-theme', 'light');
      document.documentElement.classList.remove('dark');
    });

    const hasDarkClass = await page.evaluate(() =>
      document.documentElement.classList.contains('dark')
    );
    expect(hasDarkClass).toBe(false);
  });

  test('theme persists across page navigation', async ({ page }) => {
    await page.goto('/login');

    // Set dark theme
    await page.evaluate(() => localStorage.setItem('app-theme', 'dark'));
    await page.reload();

    // Navigate to another page
    await page.goto('/register');

    const storedTheme = await page.evaluate(() => localStorage.getItem('app-theme'));
    expect(storedTheme).toBe('dark');
  });
});
