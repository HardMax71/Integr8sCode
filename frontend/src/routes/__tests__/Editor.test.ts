import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { user, mockApi } from '$test/test-utils';
import { toast } from 'svelte-sonner';
import * as meta from '$utils/meta';
import Editor from '$routes/Editor.svelte';

function createMockLimits() {
    return {
        cpu_limit: '1',
        memory_limit: '512Mi',
        cpu_request: '0.5',
        memory_request: '256Mi',
        execution_timeout: 60,
        supported_runtimes: {
            python: { versions: ['3.11', '3.12'], file_ext: 'py', display_name: 'Python' },
        },
    };
}

import {
    getK8sResourceLimitsApiV1K8sLimitsGet,
    getExampleScriptsApiV1ExampleScriptsGet,
    listSavedScriptsApiV1ScriptsGet,
    createSavedScriptApiV1ScriptsPost,
    updateSavedScriptApiV1ScriptsScriptIdPut,
    deleteSavedScriptApiV1ScriptsScriptIdDelete,
} from '$lib/api';

const mocks = vi.hoisted(() => ({
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
}));

vi.mock('$stores/auth.svelte', () => ({ authStore: mocks.mockAuthStore }));

vi.mock('$stores/userSettings.svelte', () => ({
    userSettingsStore: {
        settings: null,
        editorSettings: { font_size: 14, tab_size: 4, use_tabs: false, word_wrap: true, show_line_numbers: true },
    },
}));

vi.mock('$lib/editor', () => ({ createExecutionState: () => mocks.mockExecutionState }));

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
        css: { code: '', map: null },
        head: '',
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
        vi.spyOn(meta, 'updateMetaTags');
        vi.stubGlobal('confirm', mocks.mockConfirm);
        mocks.mockAuthStore.isAuthenticated = true;
        mocks.mockAuthStore.verifyAuth.mockResolvedValue(true);
        mocks.mockExecutionState.phase = 'idle';
        mocks.mockExecutionState.isExecuting = false;
        mocks.mockExecutionState.result = null;
        mocks.mockExecutionState.error = null;

        mockApi(getK8sResourceLimitsApiV1K8sLimitsGet).ok(createMockLimits());
        mockApi(getExampleScriptsApiV1ExampleScriptsGet).ok({ scripts: { python: '  print("Hello")' } });
        mockApi(listSavedScriptsApiV1ScriptsGet).ok({ scripts: [] });
        mockApi(createSavedScriptApiV1ScriptsPost).ok({ script_id: 'new-1' });
        mockApi(updateSavedScriptApiV1ScriptsScriptIdPut).ok({});
        mockApi(deleteSavedScriptApiV1ScriptsScriptIdDelete).ok({});
    });

    afterEach(() => vi.unstubAllGlobals());

    function renderEditor() {
        return render(Editor);
    }

    describe('Mount', () => {
        it('calls verifyAuth, getK8sLimits, and getExampleScripts on mount', async () => {
            await renderEditor();
            await waitFor(() => {
                expect(mocks.mockAuthStore.verifyAuth).toHaveBeenCalled();
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
                expect(vi.mocked(getExampleScriptsApiV1ExampleScriptsGet)).toHaveBeenCalled();
            });
        });

        it('calls listSavedScripts when authenticated', async () => {
            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(listSavedScriptsApiV1ScriptsGet)).toHaveBeenCalled();
            });
        });

        it('does not call listSavedScripts when unauthenticated', async () => {
            mocks.mockAuthStore.isAuthenticated = false;
            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });
            expect(vi.mocked(listSavedScriptsApiV1ScriptsGet)).not.toHaveBeenCalled();
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
                expect(meta.updateMetaTags).toHaveBeenCalledWith(
                    'Code Editor',
                    expect.stringContaining('Online code editor'),
                );
            });
        });
    });

    describe('Save script', () => {
        it('hides Save button when not authenticated', async () => {
            mocks.mockAuthStore.isAuthenticated = false;
            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });
            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            expect(screen.queryByTitle('Save current script')).not.toBeInTheDocument();
        });

        it('creates new script via POST API when Save is clicked', async () => {
            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });

            await user.type(screen.getByLabelText('Script Name'), 'My New Script');
            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByTitle('Save current script'));

            await waitFor(() => {
                expect(vi.mocked(createSavedScriptApiV1ScriptsPost)).toHaveBeenCalledWith({
                    body: expect.objectContaining({
                        name: 'My New Script',
                        lang: 'python',
                        lang_version: '3.11',
                    }),
                });
            });
            expect(toast.success).toHaveBeenCalledWith('Script saved successfully.');
        });

        it('falls back to create when update returns 404', async () => {
            mockApi(listSavedScriptsApiV1ScriptsGet).ok({
                scripts: [
                    {
                        script_id: 'script-99',
                        name: 'Existing Script',
                        script: 'print(1)',
                        lang: 'python',
                        lang_version: '3.11',
                        description: null,
                        created_at: '2024-01-01T00:00:00Z',
                        updated_at: '2024-01-01T00:00:00Z',
                    },
                ],
            });
            vi.mocked(updateSavedScriptApiV1ScriptsScriptIdPut).mockResolvedValue({
                data: undefined,
                error: { detail: 'Not found' },
                request: new Request('http://test'),
                response: new Response(null, { status: 404 }),
            } as any);
            mockApi(createSavedScriptApiV1ScriptsPost).ok({ script_id: 'fallback-1' });

            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(listSavedScriptsApiV1ScriptsGet)).toHaveBeenCalled();
            });

            // Load saved script to set currentScriptId
            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByRole('button', { name: 'Show Saved Scripts' }));
            await waitFor(() => {
                expect(screen.getByTitle(/Load Existing Script/)).toBeInTheDocument();
            });
            await user.click(screen.getByTitle(/Load Existing Script/));
            expect(toast.info).toHaveBeenCalledWith('Loaded script: Existing Script');

            // Options closed after loadScript, reopen and click Save
            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByTitle('Save current script'));

            await waitFor(() => {
                expect(vi.mocked(updateSavedScriptApiV1ScriptsScriptIdPut)).toHaveBeenCalledWith({
                    path: { script_id: 'script-99' },
                    body: expect.objectContaining({
                        name: 'Existing Script',
                        lang: 'python',
                        lang_version: '3.11',
                    }),
                });
            });
            await waitFor(() => {
                expect(vi.mocked(createSavedScriptApiV1ScriptsPost)).toHaveBeenCalledWith({
                    body: expect.objectContaining({
                        name: 'Existing Script',
                        lang: 'python',
                        lang_version: '3.11',
                    }),
                });
            });
            expect(toast.success).toHaveBeenCalledWith('Script saved successfully.');
        });
    });

    describe('Delete script', () => {
        it('calls confirm and delete API when delete button is clicked', async () => {
            mocks.mockConfirm.mockReturnValue(true);
            mockApi(listSavedScriptsApiV1ScriptsGet).ok({
                scripts: [
                    {
                        script_id: 'script-99',
                        name: 'My Script',
                        script: 'print(1)',
                        lang: 'python',
                        lang_version: '3.11',
                        description: null,
                        created_at: '2024-01-01T00:00:00Z',
                        updated_at: '2024-01-01T00:00:00Z',
                    },
                ],
            });

            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(listSavedScriptsApiV1ScriptsGet)).toHaveBeenCalled();
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
                expect(vi.mocked(deleteSavedScriptApiV1ScriptsScriptIdDelete)).toHaveBeenCalledWith({
                    path: { script_id: 'script-99' },
                });
            });
            expect(toast.success).toHaveBeenCalledWith('Script deleted successfully.');
        });
    });

    describe('Execution', () => {
        it('calls execution.execute with script, lang, and version when Run Script is clicked', async () => {
            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });

            await user.click(screen.getByRole('button', { name: /Run Script/i }));
            expect(mocks.mockExecutionState.execute).toHaveBeenCalledWith(expect.any(String), 'python', '3.11');
        });
    });

    describe('New script', () => {
        it('calls execution.reset and shows toast when New is clicked', async () => {
            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });

            // Open options panel then click New inside ScriptActions
            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByRole('button', { name: 'New' }));
            expect(mocks.mockExecutionState.reset).toHaveBeenCalled();
            expect(toast.info).toHaveBeenCalledWith('New script started.');
        });
    });

    describe('File upload', () => {
        function createFileInput() {
            const { container } = renderEditor();
            return container.querySelector('input[type="file"]') as HTMLInputElement;
        }

        function fireFileChange(input: HTMLInputElement, file: File) {
            Object.defineProperty(input, 'files', { value: [file], writable: true });
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }

        it('rejects file > 1MB with error toast', async () => {
            const input = createFileInput();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });
            const bigFile = new File(['x'.repeat(1024 * 1024 + 1)], 'large.py', { type: 'text/plain' });
            fireFileChange(input, bigFile);
            expect(toast.error).toHaveBeenCalledWith('File too large. Maximum size is 1MB.');
        });

        it('rejects unsupported file extension with error toast', async () => {
            const input = createFileInput();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });
            const badFile = new File(['content'], 'data.csv', { type: 'text/csv' });
            fireFileChange(input, badFile);
            expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Unsupported file type'));
        });

        it('loads .py file content and shows info toast', async () => {
            const input = createFileInput();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });
            const pyFile = new File(['print("loaded")'], 'test_script.py', { type: 'text/plain' });
            fireFileChange(input, pyFile);
            await waitFor(() => {
                expect(toast.info).toHaveBeenCalledWith(
                    expect.stringContaining('Loaded python script from test_script.py'),
                );
            });
        });
    });

    describe('Example script loading', () => {
        it('loads example for selected language', async () => {
            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });
            const exampleBtn = screen.getByTitle('Load an example script for the selected language');
            await user.click(exampleBtn);
            expect(toast.info).toHaveBeenCalledWith('Loaded example script for python.');
            expect(mocks.mockExecutionState.reset).toHaveBeenCalled();
        });

        it('shows warning when no example available', async () => {
            mockApi(getExampleScriptsApiV1ExampleScriptsGet).ok({ scripts: {} });
            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });
            const exampleBtn = screen.getByTitle('Load an example script for the selected language');
            await user.click(exampleBtn);
            expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining('No example script available'));
        });
    });

    describe('Export script', () => {
        it('creates download with correct filename and extension', async () => {
            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });

            // Spy on anchor creation without replacing createElement entirely
            const mockClick = vi.fn();
            const origCreateElement = document.createElement.bind(document);
            vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
                const el = origCreateElement(tag);
                if (tag === 'a') {
                    el.click = mockClick;
                }
                return el;
            });
            const mockCreateObjectURL = vi.fn(() => 'blob:mock-url');
            const mockRevokeObjectURL = vi.fn();
            vi.stubGlobal('URL', { createObjectURL: mockCreateObjectURL, revokeObjectURL: mockRevokeObjectURL });

            await user.type(screen.getByLabelText('Script Name'), 'my_script');
            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByTitle('Download current script'));

            expect(mockCreateObjectURL).toHaveBeenCalled();
            expect(mockClick).toHaveBeenCalled();
            expect(mockRevokeObjectURL).toHaveBeenCalledWith('blob:mock-url');

            vi.mocked(document.createElement).mockRestore();
        });
    });

    describe('localStorage persistence', () => {
        it('saves script name to localStorage after changes', async () => {
            await renderEditor();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
            });

            await user.type(screen.getByLabelText('Script Name'), 'Persisted');

            // Wait for debounced localStorage write (300ms)
            await vi.advanceTimersByTimeAsync(400);

            const stored = localStorage.getItem('scriptName');
            expect(stored).toContain('Persisted');
        });
    });
});
