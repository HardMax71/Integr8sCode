import { expect, test } from './fixtures';

test('without a stored choice the theme follows a light system preference', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await page.goto('/login');
    await expect(page.locator('html')).not.toHaveClass(/\bdark\b/);
});

test('without a stored choice the theme follows a dark system preference', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto('/login');
    await expect(page.locator('html')).toHaveClass(/\bdark\b/);
});

test('the toggle overrides the system preference and the choice survives navigation and reload', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto('/login');
    const toggle = page.getByRole('button', { name: 'Toggle theme' });
    // The toggle goes from system to light, then to dark
    await toggle.click();
    await expect(page.locator('html')).not.toHaveClass(/\bdark\b/);
    await page.emulateMedia({ colorScheme: 'light' });
    await toggle.click();
    await expect(page.locator('html')).toHaveClass(/\bdark\b/);
    await page.getByRole('link', { name: 'create a new account' }).click();
    await expect(page).toHaveURL(/\/register/);
    await expect(page.locator('html')).toHaveClass(/\bdark\b/);
    await page.reload();
    await expect(page.locator('html')).toHaveClass(/\bdark\b/);
});
