import { test, expect, clearSession } from './fixtures';

test.describe('Home Page', () => {
  test.beforeEach(async ({ page }) => {
    await clearSession(page);
    await page.goto('/');
  });

  test('displays hero section with main heading', async ({ page }) => {
    await page.waitForSelector('h1');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Code, Run');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Integrate');
  });

  test('shows welcome message with product name', async ({ page }) => {
    await expect(page.getByText('Welcome to Integr8sCode')).toBeVisible();
    await expect(page.getByText('seamless online execution environment')).toBeVisible();
  });

  test('shows start coding CTA button', async ({ page }) => {
    const ctaButton = page.getByRole('link', { name: 'Start Coding Now' });
    await expect(ctaButton).toBeVisible();
    await expect(ctaButton).toHaveAttribute('href', '/editor');
  });

  test('displays features section', async ({ page }) => {
    await expect(page.getByText('Core Features')).toBeVisible();
    await expect(page.getByText('Everything you need for quick execution')).toBeVisible();
  });

  test('shows all three feature cards', async ({ page }) => {
    await expect(page.getByText('Instant Execution')).toBeVisible();
    await expect(page.getByText('Secure & Efficient')).toBeVisible();
    await expect(page.getByText('Real-time Results')).toBeVisible();
  });
});

test.describe('Home Page Header', () => {
  test.beforeEach(async ({ page }) => {
    await clearSession(page);
    await page.goto('/');
  });

  test('shows header with logo', async ({ page }) => {
    await expect(page.locator('header')).toBeVisible();
    await expect(page.locator('header').getByText('Integr8sCode')).toBeVisible();
  });

  test('logo links to home page', async ({ page }) => {
    const logoLink = page.locator('header a').filter({ hasText: 'Integr8sCode' });
    await expect(logoLink).toHaveAttribute('href', '/');
  });

  test('shows login and register buttons when not authenticated', async ({ page }) => {
    await expect(page.locator('header').getByRole('link', { name: 'Login' })).toBeVisible();
    await expect(page.locator('header').getByRole('link', { name: 'Register' })).toBeVisible();
  });

  test('shows theme toggle button', async ({ page }) => {
    await expect(page.locator('header button[title="Toggle theme"]')).toBeVisible();
  });
});

test.describe('Home Page Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await clearSession(page);
    await page.goto('/');
  });

  test('clicking CTA navigates to login or editor', async ({ page }) => {
    await page.getByRole('link', { name: 'Start Coding Now' }).click();
    await expect(page).toHaveURL(/\/login|\/editor/);
  });

  test('can navigate to login from header', async ({ page }) => {
    await page.locator('header').getByRole('link', { name: 'Login' }).click();
    await expect(page).toHaveURL(/\/login/);
  });

  test('can navigate to register from header', async ({ page }) => {
    await page.locator('header').getByRole('link', { name: 'Register' }).click();
    await expect(page).toHaveURL(/\/register/);
  });

  test('clicking logo returns to home', async ({ page }) => {
    await page.locator('header').getByRole('link', { name: 'Login' }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.locator('header a').filter({ hasText: 'Integr8sCode' }).click();
    await expect(page).toHaveURL('/');
  });
});

test.describe('Home Page Responsive', () => {
  test('displays correctly on mobile viewport', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await clearSession(page);
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Start Coding Now' })).toBeVisible();
  });

  test('shows mobile menu button on small screens', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await clearSession(page);
    await page.goto('/');
    const menuButton = page.locator('header button').filter({ has: page.locator('svg') }).last();
    await expect(menuButton).toBeVisible();
  });

  test('can open mobile menu', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await clearSession(page);
    await page.goto('/');
    const menuButton = page.locator('header button').filter({ has: page.locator('svg') }).last();
    await menuButton.click();
    await page.waitForTimeout(300);
    // Mobile menu Login has different class than desktop - look for the visible one
    await expect(page.getByRole('link', { name: 'Login' }).locator('visible=true').first()).toBeVisible();
  });
});

test.describe('Privacy Page', () => {
  test.beforeEach(async ({ page }) => {
    await clearSession(page);
    await page.goto('/privacy');
  });

  test('displays privacy policy heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Privacy Policy' })).toBeVisible();
  });

  test('shows last updated date', async ({ page }) => {
    await expect(page.getByText('Last updated:')).toBeVisible();
  });

  test('shows key privacy sections', async ({ page }) => {
    await expect(page.getByText("Who's responsible for your data?")).toBeVisible();
    await expect(page.getByText('What information do I collect?')).toBeVisible();
    await expect(page.getByText('Your rights (GDPR stuff)')).toBeVisible();
    await expect(page.getByText('About cookies')).toBeVisible();
    await expect(page.getByText('Get in touch')).toBeVisible();
  });
});
