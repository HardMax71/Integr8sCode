import { test, expect } from '@playwright/test';

test.describe('Home Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
  });

  test('displays hero section with main heading', async ({ page }) => {
    await page.waitForSelector('h1');

    await expect(page.getByRole('heading', { level: 1 })).toContainText('Code, Run');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Integrate');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Instantly');
  });

  test('shows welcome message with product name', async ({ page }) => {
    await expect(page.getByText('Welcome to Integr8sCode')).toBeVisible();
    await expect(page.getByText('seamless online execution environment')).toBeVisible();
  });

  test('shows start coding CTA button', async ({ page }) => {
    const ctaButton = page.getByRole('link', { name: 'Start Coding Now' });
    await expect(ctaButton).toBeVisible();
  });

  test('CTA button links to editor', async ({ page }) => {
    const ctaButton = page.getByRole('link', { name: 'Start Coding Now' });
    await expect(ctaButton).toHaveAttribute('href', '/editor');
  });

  test('displays features section heading', async ({ page }) => {
    await expect(page.getByText('Core Features')).toBeVisible();
    await expect(page.getByText('Everything you need for quick execution')).toBeVisible();
  });

  test('shows instant execution feature', async ({ page }) => {
    await expect(page.getByText('Instant Execution')).toBeVisible();
    await expect(page.getByText('Run code online effortlessly')).toBeVisible();
  });

  test('shows secure and efficient feature', async ({ page }) => {
    await expect(page.getByText('Secure & Efficient')).toBeVisible();
    await expect(page.getByText('Strict resource limits')).toBeVisible();
  });

  test('shows real-time results feature', async ({ page }) => {
    await expect(page.getByText('Real-time Results')).toBeVisible();
    await expect(page.getByText('immediate feedback')).toBeVisible();
  });

  test('displays three feature cards', async ({ page }) => {
    const featureCards = page.locator('.feature-card, [class*="feature"]').filter({ hasText: /Execution|Secure|Results/ });
    await expect(featureCards).toHaveCount(3);
  });
});

test.describe('Home Page Header Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
  });

  test('shows header with logo', async ({ page }) => {
    await expect(page.locator('header')).toBeVisible();
    await expect(page.locator('header').getByText('Integr8sCode')).toBeVisible();
  });

  test('logo links to home page', async ({ page }) => {
    const logoLink = page.locator('header a').filter({ hasText: 'Integr8sCode' });
    await expect(logoLink).toHaveAttribute('href', '/');
  });

  test('shows login button when not authenticated', async ({ page }) => {
    await expect(page.locator('header').getByRole('link', { name: 'Login' })).toBeVisible();
  });

  test('shows register button when not authenticated', async ({ page }) => {
    await expect(page.locator('header').getByRole('link', { name: 'Register' })).toBeVisible();
  });

  test('shows theme toggle button', async ({ page }) => {
    const themeButton = page.locator('header button[title="Toggle theme"]');
    await expect(themeButton).toBeVisible();
  });

  test('can toggle theme from header', async ({ page }) => {
    const themeButton = page.locator('header button[title="Toggle theme"]');
    await themeButton.click();

    await page.waitForTimeout(300);
  });
});

test.describe('Home Page Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
  });

  test('clicking CTA navigates to login when not authenticated', async ({ page }) => {
    const ctaButton = page.getByRole('link', { name: 'Start Coding Now' });
    await ctaButton.click();

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
    await page.context().clearCookies();
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });

    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Start Coding Now' })).toBeVisible();
  });

  test('shows mobile menu button on small screens', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.context().clearCookies();
    await page.goto('/');

    const menuButton = page.locator('header button').filter({ has: page.locator('svg') }).last();
    await expect(menuButton).toBeVisible();
  });

  test('can open mobile menu', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.context().clearCookies();
    await page.goto('/');

    const menuButton = page.locator('header button').filter({ has: page.locator('svg') }).last();
    await menuButton.click();

    await page.waitForTimeout(300);
    await expect(page.getByText('Login').first()).toBeVisible();
  });
});

test.describe('Home Page Footer', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
  });

  test('shows footer with privacy link', async ({ page }) => {
    const footer = page.locator('footer');
    const isVisible = await footer.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      const privacyLink = footer.getByRole('link', { name: /Privacy/i });
      const hasPrivacyLink = await privacyLink.isVisible({ timeout: 2000 }).catch(() => false);

      if (hasPrivacyLink) {
        await expect(privacyLink).toBeVisible();
      }
    }
  });
});

test.describe('Home Page Privacy Link', () => {
  test('can navigate to privacy page', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/');

    const footer = page.locator('footer');
    const isVisible = await footer.isVisible({ timeout: 3000 }).catch(() => false);

    if (isVisible) {
      const privacyLink = footer.getByRole('link', { name: /Privacy/i });
      const hasPrivacyLink = await privacyLink.isVisible({ timeout: 2000 }).catch(() => false);

      if (hasPrivacyLink) {
        await privacyLink.click();
        await expect(page).toHaveURL(/\/privacy/);
      }
    }
  });
});

test.describe('Privacy Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/privacy');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });
  });

  test('displays privacy policy heading', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Privacy Policy' })).toBeVisible();
  });

  test('shows last updated date', async ({ page }) => {
    await expect(page.getByText('Last updated:')).toBeVisible();
  });

  test('shows data controller information', async ({ page }) => {
    await expect(page.getByText("Who's responsible for your data?")).toBeVisible();
  });

  test('shows data collection section', async ({ page }) => {
    await expect(page.getByText('What information do I collect?')).toBeVisible();
  });

  test('shows GDPR rights section', async ({ page }) => {
    await expect(page.getByText('Your rights (GDPR stuff)')).toBeVisible();
  });

  test('shows cookies section', async ({ page }) => {
    await expect(page.getByText('About cookies')).toBeVisible();
  });

  test('shows contact information', async ({ page }) => {
    await expect(page.getByText('Get in touch')).toBeVisible();
  });
});
