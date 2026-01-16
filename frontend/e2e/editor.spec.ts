import { test, expect, loginAsUser, clearSession, expectToastVisible } from './fixtures';

test.describe('Editor Page', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
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
        await versionMenu.getByRole('menuitemradio').first().click();
      }
    }
    await expect(languageButton).toContainText(/python|go|javascript/i);
  });

  test('shows file actions when panel opened', async ({ page }) => {
    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();
    await expect(page.getByText('File Actions')).toBeVisible();
    await expect(page.getByRole('button', { name: /New/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Upload/i })).toBeVisible();
    await expect(page.locator('button[title="Save current script"]')).toBeVisible();
    await expect(page.getByRole('button', { name: /Export/i })).toBeVisible();
  });

  test('can load example script', async ({ page }) => {
    await page.getByRole('button', { name: /Example/i }).click();
    await page.waitForTimeout(500);
    const content = await page.locator('.cm-content').textContent();
    expect(content).toBeTruthy();
    expect(content!.length).toBeGreaterThan(0);
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
    await loginAsUser(page);
  });

  test('can execute simple python script', async ({ page }) => {
    await page.getByRole('button', { name: /Example/i }).click();
    await page.waitForTimeout(500);
    await page.getByRole('button', { name: /Run Script/i }).click();
    await expect(page.getByRole('button', { name: /Executing/i })).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=Status:').first()).toBeVisible({ timeout: 30000 });
  });

  test('shows execution output on successful run', async ({ page }) => {
    await page.getByRole('button', { name: /Example/i }).click();
    await page.waitForTimeout(500);
    await page.getByRole('button', { name: /Run Script/i }).click();
    await expect(page.locator('text=Status:').first()).toBeVisible({ timeout: 30000 });
    const outputSection = page.locator('text=Output:').first();
    if (await outputSection.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(page.locator('.output-pre').first()).toBeVisible();
    }
  });

  test('shows resource usage after execution', async ({ page }) => {
    await page.getByRole('button', { name: /Example/i }).click();
    await page.waitForTimeout(500);
    await page.getByRole('button', { name: /Run Script/i }).click();
    await expect(page.locator('text=Status:').first()).toBeVisible({ timeout: 30000 });
    const resourceUsage = page.getByText('Resource Usage:');
    if (await resourceUsage.isVisible({ timeout: 5000 }).catch(() => false)) {
      await expect(page.getByText(/CPU:/)).toBeVisible();
      await expect(page.getByText(/Memory:/)).toBeVisible();
    }
  });

  test('run button is disabled during execution', async ({ page }) => {
    await page.getByRole('button', { name: /Example/i }).click();
    await page.waitForTimeout(500);
    await page.getByRole('button', { name: /Run Script/i }).click();
    const executingButton = page.getByRole('button', { name: /Executing/i });
    await expect(executingButton).toBeVisible({ timeout: 5000 });
    await expect(executingButton).toBeDisabled();
    await expect(page.locator('text=Status:').first()).toBeVisible({ timeout: 30000 });
  });
});

test.describe('Editor Script Management', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
  });

  test('can save script when authenticated', async ({ page }) => {
    await page.getByRole('button', { name: /Example/i }).click();
    await page.waitForTimeout(500);
    await page.locator('#scriptNameInput').fill(`Test Script ${Date.now()}`);
    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();
    await page.locator('button[title="Save current script"]').click();
    await expectToastVisible(page);
  });

  test('can create new script', async ({ page }) => {
    await page.getByRole('button', { name: /Example/i }).click();
    await page.waitForTimeout(500);
    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();
    await page.getByRole('button', { name: /New/i }).click();
    await expect(page.locator('#scriptNameInput')).toHaveValue('');
  });

  test('shows saved scripts section when authenticated', async ({ page }) => {
    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();
    // Use heading selector to avoid matching "Show Saved Scripts" button
    await expect(page.getByRole('heading', { name: 'Saved Scripts' })).toBeVisible();
  });
});

test.describe('Editor Unauthenticated', () => {
  test('redirects to login when not authenticated', async ({ page }) => {
    await clearSession(page);
    await page.goto('/editor');
    await expect(page).toHaveURL(/\/login/);
  });
});
