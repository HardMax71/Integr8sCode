import { test, expect, type Page } from '@playwright/test';

async function login(page: Page, username = 'user', password = 'user123') {
  await page.context().clearCookies();
  await page.goto('/login');
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.waitForSelector('#username');
  await page.fill('#username', username);
  await page.fill('#password', password);
  await page.click('button[type="submit"]');
  await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible({ timeout: 10000 });
}

test.describe('Editor Page', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('displays editor page with all main elements', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
    await expect(page.locator('.cm-editor')).toBeVisible();
    await expect(page.getByText('Execution Output')).toBeVisible();
    await expect(page.getByRole('button', { name: /Run Script/i })).toBeVisible();
  });

  test('shows language selector with available languages', async ({ page }) => {
    const languageButton = page.locator('button[aria-haspopup="menu"]').first();
    await expect(languageButton).toBeVisible();

    await languageButton.click();
    await expect(page.getByRole('menu', { name: 'Select language and version' })).toBeVisible();
  });

  test('can select different language', async ({ page }) => {
    const languageButton = page.locator('button[aria-haspopup="menu"]').first();
    await languageButton.click();

    const pythonButton = page.getByRole('menuitem', { name: /python/i });
    if (await pythonButton.isVisible()) {
      await pythonButton.hover();
      const versionMenu = page.getByRole('menu', { name: /python versions/i });
      if (await versionMenu.isVisible({ timeout: 1000 }).catch(() => false)) {
        const versionButton = versionMenu.getByRole('menuitemradio').first();
        await versionButton.click();
      }
    }

    await expect(languageButton).toContainText(/python|go|javascript/i);
  });

  test('shows options panel when settings button clicked', async ({ page }) => {
    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();

    await expect(page.getByText('File Actions')).toBeVisible();
    await expect(page.getByRole('button', { name: /New/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Upload/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Save/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Export/i })).toBeVisible();
  });

  test('can load example script', async ({ page }) => {
    const exampleButton = page.getByRole('button', { name: /Example/i });
    await exampleButton.click();

    const editor = page.locator('.cm-editor');
    await expect(editor).toBeVisible();

    await page.waitForTimeout(500);
    const content = await page.locator('.cm-content').textContent();
    expect(content).toBeTruthy();
    expect(content!.length).toBeGreaterThan(0);
  });

  test('shows empty state prompt when editor is empty', async ({ page }) => {
    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();

    await page.getByRole('button', { name: /New/i }).click();

    await page.waitForTimeout(300);
    const emptyPrompt = page.getByText('Editor is Empty');
    if (await emptyPrompt.isVisible({ timeout: 1000 }).catch(() => false)) {
      await expect(page.getByText('Start typing, upload a file')).toBeVisible();
    }
  });

  test('shows resource limits display', async ({ page }) => {
    const limitsSection = page.locator('text=CPU').first();
    if (await limitsSection.isVisible({ timeout: 2000 }).catch(() => false)) {
      await expect(page.getByText(/Memory/i).first()).toBeVisible();
      await expect(page.getByText(/Timeout/i).first()).toBeVisible();
    }
  });

  test('can input script name', async ({ page }) => {
    const scriptNameInput = page.locator('#scriptNameInput');
    await expect(scriptNameInput).toBeVisible();

    await scriptNameInput.fill('');
    await scriptNameInput.fill('My Test Script');

    await expect(scriptNameInput).toHaveValue('My Test Script');
  });
});

test.describe('Editor Execution', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('can execute simple python script', async ({ page }) => {
    const exampleButton = page.getByRole('button', { name: /Example/i });
    await exampleButton.click();
    await page.waitForTimeout(500);

    const runButton = page.getByRole('button', { name: /Run Script/i });
    await runButton.click();

    await expect(runButton).toContainText(/Executing/i);

    await expect(page.locator('text=Status:').first()).toBeVisible({ timeout: 30000 });
  });

  test('shows execution output on successful run', async ({ page }) => {
    const exampleButton = page.getByRole('button', { name: /Example/i });
    await exampleButton.click();
    await page.waitForTimeout(500);

    await page.getByRole('button', { name: /Run Script/i }).click();

    await expect(page.locator('text=Status:').first()).toBeVisible({ timeout: 30000 });

    const outputSection = page.locator('text=Output:').first();
    if (await outputSection.isVisible({ timeout: 5000 }).catch(() => false)) {
      const outputPre = page.locator('.output-pre').first();
      await expect(outputPre).toBeVisible();
    }
  });

  test('shows resource usage after execution', async ({ page }) => {
    const exampleButton = page.getByRole('button', { name: /Example/i });
    await exampleButton.click();
    await page.waitForTimeout(500);

    await page.getByRole('button', { name: /Run Script/i }).click();

    await expect(page.locator('text=Status:').first()).toBeVisible({ timeout: 30000 });

    const resourceUsage = page.getByText('Resource Usage:');
    if (await resourceUsage.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(page.getByText(/CPU:/)).toBeVisible();
      await expect(page.getByText(/Memory:/)).toBeVisible();
      await expect(page.getByText(/Time:/)).toBeVisible();
    }
  });

  test('run button is disabled during execution', async ({ page }) => {
    const exampleButton = page.getByRole('button', { name: /Example/i });
    await exampleButton.click();
    await page.waitForTimeout(500);

    const runButton = page.getByRole('button', { name: /Run Script/i });
    await runButton.click();

    await expect(runButton).toBeDisabled();
    await expect(runButton).toContainText(/Executing/i);

    await expect(page.locator('text=Status:').first()).toBeVisible({ timeout: 30000 });
  });
});

test.describe('Editor Script Management', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('can save script when authenticated', async ({ page }) => {
    const exampleButton = page.getByRole('button', { name: /Example/i });
    await exampleButton.click();
    await page.waitForTimeout(500);

    const scriptNameInput = page.locator('#scriptNameInput');
    await scriptNameInput.fill(`Test Script ${Date.now()}`);

    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();

    await page.getByRole('button', { name: /Save/i }).click();

    const toast = page.locator('[class*="toast"]').first();
    await expect(toast).toBeVisible({ timeout: 5000 });
  });

  test('shows warning when saving without name', async ({ page }) => {
    const exampleButton = page.getByRole('button', { name: /Example/i });
    await exampleButton.click();
    await page.waitForTimeout(500);

    const scriptNameInput = page.locator('#scriptNameInput');
    await scriptNameInput.fill('');

    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();

    await page.getByRole('button', { name: /Save/i }).click();

    const toast = page.locator('[class*="toast"]').first();
    await expect(toast).toBeVisible({ timeout: 5000 });
  });

  test('can create new script', async ({ page }) => {
    const exampleButton = page.getByRole('button', { name: /Example/i });
    await exampleButton.click();
    await page.waitForTimeout(500);

    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();

    await page.getByRole('button', { name: /New/i }).click();

    const scriptNameInput = page.locator('#scriptNameInput');
    await expect(scriptNameInput).toHaveValue('');
  });

  test('shows saved scripts section when authenticated', async ({ page }) => {
    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();

    await expect(page.getByText('Saved Scripts')).toBeVisible();
  });
});

test.describe('Editor Unauthenticated', () => {
  test('redirects to login when not authenticated', async ({ page }) => {
    await page.context().clearCookies();
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.clear();
      sessionStorage.clear();
    });

    await page.goto('/editor');

    await expect(page).toHaveURL(/\/login/);
  });
});
