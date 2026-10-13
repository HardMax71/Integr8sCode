import { expect, test } from './fixtures';

test('the home page shows the hero, the call to action and the features', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Code, Run');
    await expect(page.getByText('Welcome to Integr8sCode')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Start Coding Now' })).toHaveAttribute('href', '/editor');
    await expect(page.getByText('Core Features')).toBeVisible();
    for (const feature of ['Instant Execution', 'Secure & Efficient', 'Real-time Results']) {
        await expect(page.getByText(feature)).toBeVisible();
    }
});

test('the header offers login, registration and the theme toggle to a guest', async ({ page }) => {
    await page.goto('/');
    const header = page.getByRole('banner');
    await expect(header.getByRole('link', { name: 'Integr8sCode' })).toHaveAttribute('href', '/');
    await expect(header.getByRole('link', { name: 'Login' })).toBeVisible();
    await expect(header.getByRole('link', { name: 'Register' })).toBeVisible();
    await expect(header.getByRole('button', { name: 'Toggle theme' })).toBeVisible();
});

test('the call to action sends a guest to login', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Start Coding Now' }).click();
    await expect(page).toHaveURL(/\/login/);
});

test('the header links lead to login, registration and back home', async ({ page }) => {
    await page.goto('/');
    const header = page.getByRole('banner');
    await header.getByRole('link', { name: 'Register' }).click();
    await expect(page).toHaveURL(/\/register/);
    await header.getByRole('link', { name: 'Login' }).click();
    await expect(page).toHaveURL(/\/login/);
    await header.getByRole('link', { name: 'Integr8sCode' }).click();
    await expect(page).toHaveURL('/');
});

test('the mobile menu opens with the guest links', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'Start Coding Now' })).toBeVisible();
    await page.getByRole('button', { name: 'Open menu' }).click();
    const menu = page.getByTestId('mobile-menu');
    await expect(menu.getByRole('link', { name: 'Login' })).toBeVisible();
    await expect(menu.getByRole('link', { name: 'Register' })).toBeVisible();
});

test('the privacy page shows its sections', async ({ page }) => {
    await page.goto('/privacy');
    await expect(page.getByRole('heading', { name: 'Privacy Policy' })).toBeVisible();
    await expect(page.getByText('Last updated:')).toBeVisible();
    for (const section of [
        "Who's responsible for your data?",
        'What information do I collect?',
        'Your rights (GDPR stuff)',
        'About cookies',
        'Get in touch',
    ]) {
        await expect(page.getByRole('heading', { name: section })).toBeVisible();
    }
});
