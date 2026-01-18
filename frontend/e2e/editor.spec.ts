import { test, expect, runExampleAndExecute, expectToastVisible, describeAuthRequired } from './fixtures';

const PATH = '/editor';

test.describe('Editor Page', () => {
  test('displays editor page with all main elements', async ({ userPage }) => {
    await userPage.goto(PATH);
    await expect(userPage.getByRole('heading', { name: 'Code Editor' })).toBeVisible();
    await expect(userPage.locator('.cm-editor')).toBeVisible();
    await expect(userPage.getByText('Execution Output')).toBeVisible();
    await expect(userPage.getByRole('button', { name: /Run Script/i })).toBeVisible();
  });

  test('shows language selector with available languages', async ({ userPage }) => {
    await userPage.goto(PATH);
    const languageButton = userPage.locator('button[aria-haspopup="menu"]').first();
    await expect(languageButton).toBeVisible();
    await languageButton.click();
    await expect(userPage.getByRole('menu', { name: 'Select language and version' })).toBeVisible();
  });

  test('can select different language', async ({ userPage }) => {
    await userPage.goto(PATH);
    const languageButton = userPage.locator('button[aria-haspopup="menu"]').first();
    await languageButton.click();
    const pythonButton = userPage.getByRole('menuitem', { name: /python/i });
    await expect(pythonButton).toBeVisible();
    await pythonButton.hover();
    const versionMenu = userPage.getByRole('menu', { name: /python versions/i });
    await expect(versionMenu).toBeVisible();
    const versionOption = versionMenu.getByRole('menuitemradio').first();
    await versionOption.click({ force: true });
    await expect(languageButton).toContainText(/python/i);
  });

  test('shows file actions when panel opened', async ({ userPage }) => {
    await userPage.goto(PATH);
    // Use the button's accessible name from sr-only text
    const optionsToggle = userPage.getByRole('button', { name: 'Toggle Script Options' });
    await expect(optionsToggle).toBeVisible();
    await optionsToggle.click();
    await expect(userPage.getByText('File Actions')).toBeVisible();
    await expect(userPage.getByRole('button', { name: /New/i })).toBeVisible();
    await expect(userPage.getByRole('button', { name: /Upload/i })).toBeVisible();
    await expect(userPage.locator('button[title="Save current script"]')).toBeVisible();
    await expect(userPage.getByRole('button', { name: /Export/i })).toBeVisible();
  });

  test('can load example script', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: /Example/i }).click();
    const editor = userPage.locator('.cm-content');
    await expect(editor).not.toBeEmpty({ timeout: 3000 });
    const content = await editor.textContent();
    expect(content).toBeTruthy();
    expect(content!.length).toBeGreaterThan(0);
  });

  test('can input script name', async ({ userPage }) => {
    await userPage.goto(PATH);
    const scriptNameInput = userPage.locator('#scriptNameInput');
    await expect(scriptNameInput).toBeVisible();
    await scriptNameInput.fill('');
    await scriptNameInput.fill('My Test Script');
    await expect(scriptNameInput).toHaveValue('My Test Script');
  });
});

test.describe('Editor Execution', () => {
  // K8s pod execution can take 15-20s in CI (pod creation + execution + result processing)
  test.describe.configure({ timeout: 30000 });

  test('can execute simple python script', async ({ userPage }) => {
    await userPage.goto(PATH);
    await runExampleAndExecute(userPage);
    await expect(userPage.locator('text=Status:').first()).toBeVisible();
  });

  test('shows execution output on successful run', async ({ userPage }) => {
    await userPage.goto(PATH);
    await runExampleAndExecute(userPage);
    await expect(userPage.locator('text=Output:').first()).toBeVisible({ timeout: 5000 });
    await expect(userPage.locator('.output-pre').first()).toBeVisible();
  });

  test('shows resource usage after execution', async ({ userPage }) => {
    await userPage.goto(PATH);
    await runExampleAndExecute(userPage);
    await expect(userPage.getByText('Resource Usage:')).toBeVisible({ timeout: 5000 });
    await expect(userPage.getByText(/CPU:/)).toBeVisible();
    await expect(userPage.getByText(/Memory:/)).toBeVisible();
  });

  test('run button is disabled during execution', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: /Example/i }).click();
    await expect(userPage.locator('.cm-content')).not.toBeEmpty({ timeout: 3000 });
    const runButton = userPage.getByRole('button', { name: /Run Script/i });
    await runButton.click();
    const executingButton = userPage.getByRole('button', { name: /Executing/i });
    await expect(executingButton).toBeVisible({ timeout: 5000 });
    await expect(executingButton).toBeDisabled();
  });
});

test.describe('Editor Script Management', () => {
  test('can save script when authenticated', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: /Example/i }).click();
    await expect(userPage.locator('.cm-content')).not.toBeEmpty({ timeout: 3000 });
    await userPage.locator('#scriptNameInput').fill(`Test Script ${Date.now()}`);
    const optionsToggle = userPage.getByRole('button', { name: 'Toggle Script Options' });
    await optionsToggle.click();
    await userPage.locator('button[title="Save current script"]').click();
    await expectToastVisible(userPage);
  });

  test('can create new script', async ({ userPage }) => {
    await userPage.goto(PATH);
    await userPage.getByRole('button', { name: /Example/i }).click();
    await expect(userPage.locator('.cm-content')).not.toBeEmpty({ timeout: 3000 });
    const optionsToggle = userPage.getByRole('button', { name: 'Toggle Script Options' });
    await optionsToggle.click();
    await userPage.getByRole('button', { name: /New/i }).click();
    await expect(userPage.locator('#scriptNameInput')).toHaveValue('');
  });

  test('shows saved scripts section when authenticated', async ({ userPage }) => {
    await userPage.goto(PATH);
    const optionsToggle = userPage.getByRole('button', { name: 'Toggle Script Options' });
    await optionsToggle.click();
    await expect(userPage.getByRole('heading', { name: 'Saved Scripts' })).toBeVisible();
  });
});

describeAuthRequired(test, PATH);
