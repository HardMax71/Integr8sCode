import { test, expect, loginAsUser, runExampleAndExecute, expectToastVisible, describeAuthRequired } from './fixtures';

const PATH = '/editor';

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
    await expect(pythonButton).toBeVisible();
    await pythonButton.hover();
    const versionMenu = page.getByRole('menu', { name: /python versions/i });
    await expect(versionMenu).toBeVisible();
    const versionOption = versionMenu.getByRole('menuitemradio').first();
    await versionOption.click({ force: true });
    await expect(languageButton).toContainText(/python/i);
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
    const editor = page.locator('.cm-content');
    await expect(editor).not.toBeEmpty({ timeout: 3000 });
    const content = await editor.textContent();
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
    await runExampleAndExecute(page);
    await expect(page.locator('text=Status:').first()).toBeVisible();
  });

  test('shows execution output on successful run', async ({ page }) => {
    await runExampleAndExecute(page);
    await expect(page.locator('text=Output:').first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('.output-pre').first()).toBeVisible();
  });

  test('shows resource usage after execution', async ({ page }) => {
    await runExampleAndExecute(page);
    await expect(page.getByText('Resource Usage:')).toBeVisible({ timeout: 5000 });
    await expect(page.getByText(/CPU:/)).toBeVisible();
    await expect(page.getByText(/Memory:/)).toBeVisible();
  });

  test('run button is disabled during execution', async ({ page }) => {
    await page.getByRole('button', { name: /Example/i }).click();
    await expect(page.locator('.cm-content')).not.toBeEmpty({ timeout: 3000 });
    const runButton = page.getByRole('button', { name: /Run Script/i });
    await runButton.click();
    const executingButton = page.getByRole('button', { name: /Executing/i });
    await expect(executingButton).toBeVisible({ timeout: 5000 });
    await expect(executingButton).toBeDisabled();
  });
});

test.describe('Editor Script Management', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsUser(page);
  });

  test('can save script when authenticated', async ({ page }) => {
    await page.getByRole('button', { name: /Example/i }).click();
    await expect(page.locator('.cm-content')).not.toBeEmpty({ timeout: 3000 });
    await page.locator('#scriptNameInput').fill(`Test Script ${Date.now()}`);
    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();
    await page.locator('button[title="Save current script"]').click();
    await expectToastVisible(page);
  });

  test('can create new script', async ({ page }) => {
    await page.getByRole('button', { name: /Example/i }).click();
    await expect(page.locator('.cm-content')).not.toBeEmpty({ timeout: 3000 });
    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();
    await page.getByRole('button', { name: /New/i }).click();
    await expect(page.locator('#scriptNameInput')).toHaveValue('');
  });

  test('shows saved scripts section when authenticated', async ({ page }) => {
    const settingsButton = page.locator('button[aria-expanded]').filter({ hasText: '' }).last();
    await settingsButton.click();
    await expect(page.getByRole('heading', { name: 'Saved Scripts' })).toBeVisible();
  });
});

describeAuthRequired(test, PATH);
