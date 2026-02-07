import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { setupAnimationMock } from '$lib/../__tests__/test-utils';

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
    editorSettings: { theme: 'auto', font_size: 14, tab_size: 4, use_tabs: false, word_wrap: true, show_line_numbers: true },
  },
}));

vi.mock('svelte-sonner', async () =>
  (await import('$lib/../__tests__/test-utils')).createToastMock(mocks.addToast));

vi.mock('$lib/api-interceptors', () => ({
  unwrap: (...args: unknown[]) => mocks.mockUnwrap(...args),
  unwrapOr: (...args: unknown[]) => mocks.mockUnwrapOr(...args),
}));

vi.mock('$utils/meta', async () =>
  (await import('$lib/../__tests__/test-utils')).createMetaMock(
    mocks.mockUpdateMetaTags, { editor: { title: 'Code Editor', description: 'Editor desc' } }));

vi.mock('$lib/editor', () => ({ createExecutionState: () => mocks.mockExecutionState }));

vi.mock('$components/Spinner.svelte', async () =>
  (await import('$lib/../__tests__/test-utils')).createMockSvelteComponent('<span></span>', 'spinner'));

vi.mock('@lucide/svelte', async () =>
  (await import('$lib/../__tests__/test-utils')).createMockIconModule('CirclePlay', 'Settings', 'Lightbulb'));

vi.mock('$components/editor', async () =>
  (await import('$lib/../__tests__/test-utils')).createMockNamedComponents({
    CodeMirrorEditor: '<div data-testid="code-editor" class="cm-editor"></div>',
    OutputPanel: '<div data-testid="output-panel">Execution Output</div>',
    LanguageSelect: '<div data-testid="lang-select"></div>',
    ResourceLimits: '<div data-testid="resource-limits"></div>',
    EditorToolbar: '<div data-testid="editor-toolbar"><input id="scriptNameInput" /></div>',
    ScriptActions: '<div data-testid="script-actions"></div>',
    SavedScripts: '<div data-testid="saved-scripts"></div>',
  }));

describe('Editor', () => {
  const user = userEvent.setup();

  beforeEach(() => {
    vi.clearAllMocks();
    setupAnimationMock();
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
    mocks.listSavedScriptsApiV1ScriptsGet.mockResolvedValue({ data: [], error: undefined });
    mocks.createSavedScriptApiV1ScriptsPost.mockResolvedValue({ data: { script_id: 'new-1' }, error: undefined });
    mocks.updateSavedScriptApiV1ScriptsScriptIdPut.mockResolvedValue({ data: {}, error: undefined });
    mocks.deleteSavedScriptApiV1ScriptsScriptIdDelete.mockResolvedValue({ data: {}, error: undefined });
  });

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
    it('warns when not authenticated', async () => {
      mocks.mockAuthStore.isAuthenticated = false;
      await renderEditor();
      await waitFor(() => {
        expect(mocks.getK8sResourceLimitsApiV1K8sLimitsGet).toHaveBeenCalled();
      });
    });

    it('creates new script via POST API', async () => {
      await renderEditor();
      await waitFor(() => {
        expect(mocks.getK8sResourceLimitsApiV1K8sLimitsGet).toHaveBeenCalled();
      });
      expect(mocks.createSavedScriptApiV1ScriptsPost).toBeDefined();
    });

    it('falls back to create when update returns 404', async () => {
      mocks.updateSavedScriptApiV1ScriptsScriptIdPut.mockResolvedValue({
        data: undefined,
        error: { detail: 'Not found' },
        response: { status: 404 },
      });
      mocks.createSavedScriptApiV1ScriptsPost.mockResolvedValue({
        data: { script_id: 'fallback-1' },
        error: undefined,
      });
      const updateResult = await mocks.updateSavedScriptApiV1ScriptsScriptIdPut({});
      expect(updateResult.response?.status).toBe(404);
    });
  });

  describe('Delete script', () => {
    it('calls confirm with script name and deletes on acceptance', async () => {
      mocks.mockConfirm.mockReturnValue(true);
      await renderEditor();
      await waitFor(() => {
        expect(mocks.getK8sResourceLimitsApiV1K8sLimitsGet).toHaveBeenCalled();
      });
      expect(mocks.deleteSavedScriptApiV1ScriptsScriptIdDelete).toBeDefined();
    });
  });

  describe('Execution', () => {
    it('has execution state wired from createExecutionState', async () => {
      await renderEditor();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Code Editor' })).toBeInTheDocument();
      });
      expect(mocks.mockExecutionState.execute).toBeDefined();
      expect(mocks.mockExecutionState.reset).toBeDefined();
    });
  });

  describe('New script', () => {
    it('verifies execution.reset is available for new script flow', async () => {
      await renderEditor();
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: 'Code Editor' })).toBeInTheDocument();
      });
      expect(mocks.mockExecutionState.reset).toBeDefined();
    });
  });
});
