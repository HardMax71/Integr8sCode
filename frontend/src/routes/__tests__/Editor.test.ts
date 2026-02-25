import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { user } from '$test/test-utils';

function createMockLimits() {
  return {
    max_cpu: '1',
    max_memory: '512Mi',
    max_timeout: 60,
    supported_runtimes: {
      python: { versions: ['3.11', '3.12'], file_ext: 'py', display_name: 'Python' },
    },
  };
}

const mocks = vi.hoisted(() => ({
  getK8sResourceLimitsApiV1K8sLimitsGet: vi.fn(),
  getExampleScriptsApiV1ExampleScriptsGet: vi.fn(),
  listSavedScriptsApiV1ScriptsGet: vi.fn(),
  createSavedScriptApiV1ScriptsPost: vi.fn(),
  updateSavedScriptApiV1ScriptsScriptIdPut: vi.fn(),
  deleteSavedScriptApiV1ScriptsScriptIdDelete: vi.fn(),
  addToast: vi.fn(),
  mockConfirm: vi.fn(),
  mockExecutionState: {
    phase: 'idle' as string,
    result: null as unknown,
    error: null as string | null,
    isExecuting: false,
    execute: vi.fn(),
    abort: vi.fn(),
    reset: vi.fn(),
  },
  mockAuthStore: {
    isAuthenticated: true,
    username: 'testuser',
    userRole: 'user',
    verifyAuth: vi.fn().mockResolvedValue(true),
  },
  mockUnwrap: vi.fn((result: { data?: unknown; error?: unknown }) => {
    if (result.error) throw result.error;
    return result.data;
  }),
  mockUnwrapOr: vi.fn((result: { data?: unknown; error?: unknown }, fallback: unknown) => {
    return result.error ? fallback : result.data ?? fallback;
  }),
  mockUpdateMetaTags: vi.fn(),
}));

vi.mock('$lib/api', () => ({
  getK8sResourceLimitsApiV1K8sLimitsGet: (...args: unknown[]) => mocks.getK8sResourceLimitsApiV1K8sLimitsGet(...args),
  getExampleScriptsApiV1ExampleScriptsGet: (...args: unknown[]) => mocks.getExampleScriptsApiV1ExampleScriptsGet(...args),
  listSavedScriptsApiV1ScriptsGet: (...args: unknown[]) => mocks.listSavedScriptsApiV1ScriptsGet(...args),
  createSavedScriptApiV1ScriptsPost: (...args: unknown[]) => mocks.createSavedScriptApiV1ScriptsPost(...args),
  updateSavedScriptApiV1ScriptsScriptIdPut: (...args: unknown[]) => mocks.updateSavedScriptApiV1ScriptsScriptIdPut(...args),
  deleteSavedScriptApiV1ScriptsScriptIdDelete: (...args: unknown[]) => mocks.deleteSavedScriptApiV1ScriptsScriptIdDelete(...args),
}));

vi.mock('$stores/auth.svelte', () => ({ authStore: mocks.mockAuthStore }));

vi.mock('$stores/userSettings.svelte', () => ({
  userSettingsStore: {
    settings: null,
    editorSettings: { font_size: 14, tab_size: 4, use_tabs: false, word_wrap: true, show_line_numbers: true },
  },
}));

vi.mock('svelte-sonner', async () =>
  (await import('$test/test-utils')).createToastMock(mocks.addToast));

vi.mock('$lib/api-interceptors', () => ({
  unwrap: (...args: unknown[]) => (mocks.mockUnwrap as (...a: unknown[]) => unknown)(...args),
  unwrapOr: (...args: unknown[]) => (mocks.mockUnwrapOr as (...a: unknown[]) => unknown)(...args),
}));

vi.mock('$utils/meta', async () =>
  (await import('$test/test-utils')).createMetaMock(
    mocks.mockUpdateMetaTags, { editor: { title: 'Code Editor', description: 'Editor desc' } }));

vi.mock('$lib/editor', () => ({ createExecutionState: () => mocks.mockExecutionState }));

vi.mock('$components/Spinner.svelte', async () =>
  (await import('$test/test-utils')).createMockSvelteComponent('<span></span>', 'spinner'));

vi.mock('@lucide/svelte', async () =>
  (await import('$test/test-utils')).createMockIconModule(
    'CirclePlay', 'Settings', 'Lightbulb',
    'FilePlus', 'Upload', 'Download', 'Save',
    'List', 'Trash2'));

vi.mock('$components/editor', async () => {
  const utils = await import('$test/test-utils');
  const components = utils.createMockNamedComponents({
    OutputPanel: '<div data-testid="output-panel">Execution Output</div>',
    LanguageSelect: '<div data-testid="lang-select"></div>',
    ResourceLimits: '<div data-testid="resource-limits"></div>',
  });
  // CodeMirrorEditor needs setContent for bind:this usage in newScript/loadScript
  const CodeMirrorEditor = function () {
    return { setContent() {} };
  } as unknown as { new (): object; render: () => { html: string; css: { code: string; map: null }; head: string } };
  CodeMirrorEditor.render = () => ({
    html: '<div data-testid="code-editor" class="cm-editor"></div>',
    css: { code: '', map: null }, head: '',
  });
  components.CodeMirrorEditor = CodeMirrorEditor;
  const { default: EditorToolbar } = await import('$components/editor/EditorToolbar.svelte');
  components.EditorToolbar = EditorToolbar;
  const { default: ScriptActions } = await import('$components/editor/ScriptActions.svelte');
  components.ScriptActions = ScriptActions;
  const { default: SavedScripts } = await import('$components/editor/SavedScripts.svelte');
  components.SavedScripts = SavedScripts;
  return components;
});

describe('Editor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.stubGlobal('confirm', mocks.mockConfirm);
    mocks.mockAuthStore.isAuthenticated = true;
    mocks.mockAuthStore.verifyAuth.mockResolvedValue(true);
    mocks.mockExecutionState.phase = 'idle';
    mocks.mockExecutionState.isExecuting = false;
    mocks.mockExecutionState.result = null;
    mocks.mockExecutionState.error = null;

    mocks.getK8sResourceLimitsApiV1K8sLimitsGet.mockResolvedValue({
      data: createMockLimits(),
      error: undefined,
    });
    mocks.getExampleScriptsApiV1ExampleScriptsGet.mockResolvedValue({
      data: { scripts: { python: '  print("Hello")' } },
      error: undefined,
    });
    mocks.listSavedScriptsApiV1ScriptsGet.mockResolvedValue({ data: { scripts: [] }, error: undefined });
    mocks.createSavedScriptApiV1ScriptsPost.mockResolvedValue({ data: { script_id: 'new-1' }, error: undefined });
    mocks.updateSavedScriptApiV1ScriptsScriptIdPut.mockResolvedValue({ data: {}, error: undefined });
    mocks.deleteSavedScriptApiV1ScriptsScriptIdDelete.mockResolvedValue({ data: {}, error: undefined });
  });

  afterEach(() => vi.unstubAllGlobals());

  async function renderEditor() {
    const { default: Editor } = await import('$routes/Editor.svelte');
    return render(Editor);
  }

  describe('Mount', () => {
    it('calls verifyAuth, getK8sLimits, and getExampleScripts on mount', async () => {
      await renderEditor();
      await waitFor(() => {
        expect(mocks.mockAuthStore.verifyAuth).toHaveBeenCalled();
        expect(mocks.getK8sResourceLimitsApiV1K8sLimitsGet).toHaveBeenCalled();
        expect(mocks.getExampleScriptsApiV1ExampleScriptsGet).toHaveBeenCalled();
      });
    });

    it('calls listSavedScripts when authenticated', async () => {
      await renderEditor();
      await waitFor(() => {
        expect(mocks.listSavedScriptsApiV1ScriptsGet).toHaveBeenCalled();
      });
    });

    it('does not call listSavedScripts when unauthenticated', async () => {
      mocks.mockAuthStore.isAuthenticated = false;
      await renderEditor();
      await waitFor(() => {
        expect(mocks.getK8sResourceLimitsApiV1K8sLimitsGet).toHaveBeenCalled();
      });
      expect(mocks.listSavedScriptsApiV1ScriptsGet).not.toHaveBeenCalled();
    });

    it('renders page heading "Code Editor"', async () => {
      await renderEditor();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Code Editor' })).toBeInTheDocument();
      });
    });

    it('calls updateMetaTags with editor meta', async () => {
      await renderEditor();
      await waitFor(() => {
        expect(mocks.mockUpdateMetaTags).toHaveBeenCalledWith('Code Editor', 'Editor desc');
      });
    });
  });

  describe('Save script', () => {
    it('hides Save button when not authenticated', async () => {
      mocks.mockAuthStore.isAuthenticated = false;
      await renderEditor();
      await waitFor(() => {
        expect(mocks.getK8sResourceLimitsApiV1K8sLimitsGet).toHaveBeenCalled();
      });
      await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
      expect(screen.queryByTitle('Save current script')).not.toBeInTheDocument();
    });

    it('creates new script via POST API when Save is clicked', async () => {
      await renderEditor();
      await waitFor(() => {
        expect(mocks.getK8sResourceLimitsApiV1K8sLimitsGet).toHaveBeenCalled();
      });

      await user.type(screen.getByLabelText('Script Name'), 'My New Script');
      await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
      await user.click(screen.getByTitle('Save current script'));

      await waitFor(() => {
        expect(mocks.createSavedScriptApiV1ScriptsPost).toHaveBeenCalledWith({
          body: expect.objectContaining({
            name: 'My New Script',
            lang: 'python',
            lang_version: '3.11',
          }),
        });
      });
      expect(mocks.addToast).toHaveBeenCalledWith('success', 'Script saved successfully.');
    });

    it('falls back to create when update returns 404', async () => {
      mocks.listSavedScriptsApiV1ScriptsGet.mockResolvedValue({
        data: { scripts: [{ script_id: 'script-99', name: 'Existing Script', script: 'print(1)', lang: 'python', lang_version: '3.11' }] },
        error: undefined,
      });
      mocks.updateSavedScriptApiV1ScriptsScriptIdPut.mockResolvedValue({
        data: undefined,
        error: { detail: 'Not found' },
        response: { status: 404 },
      });
      mocks.createSavedScriptApiV1ScriptsPost.mockResolvedValue({
        data: { script_id: 'fallback-1' },
        error: undefined,
      });

      await renderEditor();
      await waitFor(() => {
        expect(mocks.listSavedScriptsApiV1ScriptsGet).toHaveBeenCalled();
      });

      // Load saved script to set currentScriptId
      await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
      await user.click(screen.getByRole('button', { name: 'Show Saved Scripts' }));
      await waitFor(() => {
        expect(screen.getByTitle(/Load Existing Script/)).toBeInTheDocument();
      });
      await user.click(screen.getByTitle(/Load Existing Script/));
      expect(mocks.addToast).toHaveBeenCalledWith('info', 'Loaded script: Existing Script');

      // Options closed after loadScript, reopen and click Save
      await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
      await user.click(screen.getByTitle('Save current script'));

      await waitFor(() => {
        expect(mocks.updateSavedScriptApiV1ScriptsScriptIdPut).toHaveBeenCalledWith({
          path: { script_id: 'script-99' },
          body: expect.objectContaining({
            name: 'Existing Script',
            lang: 'python',
            lang_version: '3.11',
          }),
        });
      });
      await waitFor(() => {
        expect(mocks.createSavedScriptApiV1ScriptsPost).toHaveBeenCalledWith({
          body: expect.objectContaining({
            name: 'Existing Script',
            lang: 'python',
            lang_version: '3.11',
          }),
        });
      });
      expect(mocks.addToast).toHaveBeenCalledWith('success', 'Script saved successfully.');
    });
  });

  describe('Delete script', () => {
    it('calls confirm and delete API when delete button is clicked', async () => {
      mocks.mockConfirm.mockReturnValue(true);
      mocks.listSavedScriptsApiV1ScriptsGet.mockResolvedValue({
        data: { scripts: [{ script_id: 'script-99', name: 'My Script', script: 'print(1)', lang: 'python', lang_version: '3.11' }] },
        error: undefined,
      });

      await renderEditor();
      await waitFor(() => {
        expect(mocks.listSavedScriptsApiV1ScriptsGet).toHaveBeenCalled();
      });

      // Open options panel, then expand saved scripts list
      await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
      await user.click(screen.getByRole('button', { name: 'Show Saved Scripts' }));
      await waitFor(() => {
        expect(screen.getByTitle('Delete My Script')).toBeInTheDocument();
      });

      await user.click(screen.getByTitle('Delete My Script'));
      expect(mocks.mockConfirm).toHaveBeenCalledWith('Are you sure you want to delete "My Script"?');
      await waitFor(() => {
        expect(mocks.deleteSavedScriptApiV1ScriptsScriptIdDelete).toHaveBeenCalledWith({
          path: { script_id: 'script-99' },
        });
      });
      expect(mocks.addToast).toHaveBeenCalledWith('success', 'Script deleted successfully.');
    });
  });

  describe('Execution', () => {
    it('calls execution.execute with script, lang, and version when Run Script is clicked', async () => {
      await renderEditor();
      await waitFor(() => {
        expect(mocks.getK8sResourceLimitsApiV1K8sLimitsGet).toHaveBeenCalled();
      });

      await user.click(screen.getByRole('button', { name: /Run Script/i }));
      expect(mocks.mockExecutionState.execute).toHaveBeenCalledWith(
        expect.any(String), 'python', '3.11',
      );
    });
  });

  describe('New script', () => {
    it('calls execution.reset and shows toast when New is clicked', async () => {
      await renderEditor();
      await waitFor(() => {
        expect(mocks.getK8sResourceLimitsApiV1K8sLimitsGet).toHaveBeenCalled();
      });

      // Open options panel then click New inside ScriptActions
      await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
      await user.click(screen.getByRole('button', { name: 'New' }));
      expect(mocks.mockExecutionState.reset).toHaveBeenCalled();
      expect(mocks.addToast).toHaveBeenCalledWith('info', 'New script started.');
    });
  });
});
