import {
  test, expect, runExampleAndExecute, expectToastVisible, describeAuthRequired,
  loadExampleScript, openScriptOptions, saveScriptAs, expandSavedScripts,
} from './fixtures';

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
    const languageButton = userPage.getByRole('button', { name: 'Select language and version' });
    await expect(languageButton).toBeVisible();
    await languageButton.click();
    await expect(userPage.getByRole('menu', { name: 'Select language and version' })).toBeVisible();
  });

  test('can select different language', async ({ userPage }) => {
    await userPage.goto(PATH);
    const languageButton = userPage.getByRole('button', { name: 'Select language and version' });
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
    await openScriptOptions(userPage);
    await expect(userPage.getByText('File Actions')).toBeVisible();
    await expect(userPage.getByRole('button', { name: /New/i })).toBeVisible();
    await expect(userPage.getByRole('button', { name: /Upload/i })).toBeVisible();
    await expect(userPage.locator('button[title="Save current script"]')).toBeVisible();
    await expect(userPage.getByRole('button', { name: /Export/i })).toBeVisible();
  });

  test('can load example script', async ({ userPage }) => {
    await userPage.goto(PATH);
    await loadExampleScript(userPage);
    const content = await userPage.locator('.cm-content').textContent();
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
    const result = await runExampleAndExecute(userPage);
    expect(result.status).toBe('completed');
    expect(result.exit_code).toBe(0);
    expect(result.stdout ?? '').toContain('Hello from a Python');
  });

  test('shows execution output on successful run', async ({ userPage }) => {
    await userPage.goto(PATH);
    const result = await runExampleAndExecute(userPage);
    await expect(userPage.getByText('Output:', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await expect(userPage.getByTestId('output-pre').first()).toContainText('Hello from a Python');
    expect(result.stdout ?? '').toContain('Hello from a Python');
  });

  test('shows resource usage after execution', async ({ userPage }) => {
    await userPage.goto(PATH);
    const result = await runExampleAndExecute(userPage);
    await expect(userPage.getByText('Resource Usage:')).toBeVisible({ timeout: 5000 });
    await expect(userPage.getByText(/CPU:/)).toBeVisible();
    await expect(userPage.getByText(/Memory:/)).toBeVisible();
    expect(result.resource_usage).toBeTruthy();
  });

  test('run button is disabled during execution', async ({ userPage }) => {
    await userPage.goto(PATH);
    await loadExampleScript(userPage);
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
    await saveScriptAs(userPage, `Test Script ${Date.now()}`);
  });

  test('can create new script', async ({ userPage }) => {
    await userPage.goto(PATH);
    await loadExampleScript(userPage);
    await openScriptOptions(userPage);
    await userPage.getByRole('button', { name: /New/i }).click();
    await expect(userPage.locator('#scriptNameInput')).toHaveValue('');
  });

  test('shows saved scripts section when authenticated', async ({ userPage }) => {
    await userPage.goto(PATH);
    await openScriptOptions(userPage);
    await expect(userPage.getByRole('heading', { name: 'Saved Scripts' })).toBeVisible();
  });

  test('can load a previously saved script', async ({ userPage }) => {
    await userPage.goto(PATH);
    const scriptName = `Load Test ${Date.now()}`;
    await saveScriptAs(userPage, scriptName);

    // Create new script to clear state
    await userPage.getByRole('button', { name: /New/i }).click();
    await expect(userPage.locator('#scriptNameInput')).toHaveValue('');

    // Expand the saved scripts list to find the saved script
    await expandSavedScripts(userPage);

    const savedScript = userPage.getByText(scriptName, { exact: true }).first();
    await expect(savedScript).toBeVisible({ timeout: 3000 });
    await savedScript.click();
    await expectToastVisible(userPage);
    await expect(userPage.locator('#scriptNameInput')).toHaveValue(scriptName);
  });

  test('can delete a saved script', async ({ userPage }) => {
    await userPage.goto(PATH);
    const scriptName = `Delete Test ${Date.now()}`;
    await saveScriptAs(userPage, scriptName);

    // Expand the saved scripts list to find the saved script
    await expandSavedScripts(userPage);

    const scriptRow = userPage.getByText(scriptName, { exact: true }).first();
    await expect(scriptRow).toBeVisible({ timeout: 3000 });
    const deleteBtn = userPage.getByRole('button', { name: `Delete ${scriptName}` });
    await expect(deleteBtn).toBeVisible({ timeout: 2000 });
    userPage.on('dialog', dialog => dialog.accept());
    await deleteBtn.click();
    await expectToastVisible(userPage);
  });

  test('can export script as file', async ({ userPage }) => {
    await userPage.goto(PATH);
    await loadExampleScript(userPage);
    await userPage.locator('#scriptNameInput').fill('export-test');
    await openScriptOptions(userPage);

    const [download] = await Promise.all([
      userPage.waitForEvent('download', { timeout: 5000 }),
      userPage.getByRole('button', { name: /Export/i }).click(),
    ]);
    expect(download.suggestedFilename()).toContain('export-test');
  });
});

describeAuthRequired(test, PATH);
