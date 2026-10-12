import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import {
    user,
    mockApi,
    renderWithQueryClient,
    createMockResourceLimits,
    createMockSavedScript,
    createMockUserSettings,
} from '#test/test-utils.ts';
import { ApiError } from '#lib/api-error.ts';
import { toast } from 'svelte-sonner';
import Editor from '#routes/(auth)/editor/+page.svelte';

import {
    getK8sResourceLimitsApiV1K8sLimitsGet,
    getExampleScriptsApiV1ExampleScriptsGet,
    listSavedScriptsApiV1ScriptsGet,
    createSavedScriptApiV1ScriptsPost,
    updateSavedScriptApiV1ScriptsScriptIdPut,
    deleteSavedScriptApiV1ScriptsScriptIdDelete,
    getUserSettingsApiV1UserSettingsGet,
} from '#lib/api/index.ts';

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
    },
}));

vi.mock('#stores/auth.svelte.ts', () => ({ authStore: mocks.mockAuthStore }));

vi.mock('#lib/editor/index.ts', () => ({
    createExecutionState: () => mocks.mockExecutionState,
}));

vi.mock('#components/editor/index.ts', async () => {
    const utils = await import('#test/test-utils.ts');
    const components = utils.createMockNamedComponents({
        OutputPanel: '<div data-testid="output-panel">Execution Output</div>',
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
    const { default: EditorToolbar } = await import('#components/editor/EditorToolbar.svelte');
    components.EditorToolbar = EditorToolbar;
    const { default: ScriptActions } = await import('#components/editor/ScriptActions.svelte');
    components.ScriptActions = ScriptActions;
    const { default: SavedScripts } = await import('#components/editor/SavedScripts.svelte');
    components.SavedScripts = SavedScripts;
    const { default: LanguageSelect } = await import('#components/editor/LanguageSelect.svelte');
    components.LanguageSelect = LanguageSelect;
    return components;
});

describe('Editor', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        localStorage.clear();
        vi.stubGlobal('confirm', mocks.mockConfirm);
        mocks.mockAuthStore.isAuthenticated = true;
        mocks.mockExecutionState.phase = 'idle';
        mocks.mockExecutionState.isExecuting = false;
        mocks.mockExecutionState.result = null;
        mocks.mockExecutionState.error = null;

        mockApi(getK8sResourceLimitsApiV1K8sLimitsGet).ok(createMockResourceLimits());
        mockApi(getExampleScriptsApiV1ExampleScriptsGet).ok({ scripts: { python: '  print("Hello")' } });
        mockApi(listSavedScriptsApiV1ScriptsGet).ok({ scripts: [] });
        mockApi(getUserSettingsApiV1UserSettingsGet).ok(createMockUserSettings());
        mockApi(createSavedScriptApiV1ScriptsPost).ok(createMockSavedScript({ script_id: 'new-1' }));
        mockApi(updateSavedScriptApiV1ScriptsScriptIdPut).ok(createMockSavedScript());
        mockApi(deleteSavedScriptApiV1ScriptsScriptIdDelete).ok();
    });

    afterEach(() => vi.unstubAllGlobals());

    function renderEditor() {
        return renderWithQueryClient(Editor);
    }

    // Run Script stays disabled until the runtimes have loaded
    async function waitForRuntimes() {
        await waitFor(() => expect(screen.getByRole('button', { name: /Run Script/i })).toBeEnabled());
    }

    describe('Mount', () => {
        it('loads the limits, the examples, the saved scripts and the user settings', async () => {
            renderEditor();
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
                expect(vi.mocked(getExampleScriptsApiV1ExampleScriptsGet)).toHaveBeenCalled();
                expect(vi.mocked(listSavedScriptsApiV1ScriptsGet)).toHaveBeenCalled();
                expect(vi.mocked(getUserSettingsApiV1UserSettingsGet)).toHaveBeenCalled();
            });
        });

        it('loads neither saved scripts nor user settings when unauthenticated', async () => {
            mocks.mockAuthStore.isAuthenticated = false;
            renderEditor();
            await waitForRuntimes();
            expect(vi.mocked(listSavedScriptsApiV1ScriptsGet)).not.toHaveBeenCalled();
            expect(vi.mocked(getUserSettingsApiV1UserSettingsGet)).not.toHaveBeenCalled();
        });

        it('renders page heading "Code Editor"', async () => {
            await renderEditor();
            await waitFor(() => {
                expect(screen.getByRole('heading', { name: 'Code Editor' })).toBeInTheDocument();
            });
        });

        it('sets the page title', async () => {
            await renderEditor();
            await waitFor(() => expect(document.title).toBe('Code Editor - Integr8sCode'));
        });
    });

    describe('Save script', () => {
        it('hides Save button when not authenticated', async () => {
            mocks.mockAuthStore.isAuthenticated = false;
            await renderEditor();
            await waitForRuntimes();
            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            expect(screen.queryByTitle('Save current script')).not.toBeInTheDocument();
        });

        it('creates new script via POST API when Save is clicked', async () => {
            await renderEditor();
            await waitForRuntimes();

            await user.type(screen.getByLabelText('Name'), 'My New Script');
            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByTitle('Save current script'));

            await waitFor(() => {
                expect(vi.mocked(createSavedScriptApiV1ScriptsPost)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        body: expect.objectContaining({
                            name: 'My New Script',
                            lang: 'python',
                            lang_version: '3.14',
                        }),
                    }),
                );
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
            vi.mocked(updateSavedScriptApiV1ScriptsScriptIdPut).mockRejectedValue(
                new ApiError(404, { detail: 'Not found' }),
            );
            mockApi(createSavedScriptApiV1ScriptsPost).ok(createMockSavedScript({ script_id: 'fallback-1' }));

            await renderEditor();
            await waitForRuntimes();

            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByRole('button', { name: 'Show Saved Scripts' }));
            await waitFor(() => {
                expect(screen.getByTitle(/Load Existing Script/)).toBeInTheDocument();
            });
            await user.click(screen.getByTitle(/Load Existing Script/));
            expect(toast.info).toHaveBeenCalledWith('Loaded script: Existing Script');

            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByTitle('Save current script'));

            await waitFor(() => {
                expect(vi.mocked(updateSavedScriptApiV1ScriptsScriptIdPut)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { script_id: 'script-99' },
                        body: expect.objectContaining({
                            name: 'Existing Script',
                            lang: 'python',
                            lang_version: '3.11',
                        }),
                    }),
                );
            });
            await waitFor(() => {
                expect(vi.mocked(createSavedScriptApiV1ScriptsPost)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        body: expect.objectContaining({
                            name: 'Existing Script',
                            lang: 'python',
                            lang_version: '3.11',
                        }),
                    }),
                );
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
            await waitForRuntimes();

            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByRole('button', { name: 'Show Saved Scripts' }));
            await waitFor(() => {
                expect(screen.getByTitle('Delete My Script')).toBeInTheDocument();
            });

            await user.click(screen.getByTitle('Delete My Script'));
            expect(mocks.mockConfirm).toHaveBeenCalledWith('Are you sure you want to delete "My Script"?');
            await waitFor(() => {
                expect(vi.mocked(deleteSavedScriptApiV1ScriptsScriptIdDelete)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { script_id: 'script-99' },
                    }),
                );
            });
            expect(toast.success).toHaveBeenCalledWith('Script deleted successfully.');
        });
    });

    describe('Execution', () => {
        it('calls execution.execute with script, lang, and version when Run Script is clicked', async () => {
            await renderEditor();
            await waitForRuntimes();

            await user.click(screen.getByRole('button', { name: /Run Script/i }));
            expect(mocks.mockExecutionState.execute).toHaveBeenCalledWith(expect.any(String), 'python', '3.14');
        });
    });

    describe('Initial language and version', () => {
        function storeSelection(lang: string, version: string) {
            localStorage.setItem('selectedLang', JSON.stringify(lang));
            localStorage.setItem('selectedVersion', JSON.stringify(version));
        }

        async function runAndExpect(lang: string, version: string) {
            await renderEditor();
            await waitFor(() => {
                expect(screen.getByRole('button', { name: 'Select language and version' })).toHaveTextContent(
                    `${lang} ${version}`,
                );
            });
            await user.click(screen.getByRole('button', { name: /Run Script/i }));
            expect(mocks.mockExecutionState.execute).toHaveBeenCalledWith(expect.any(String), lang, version);
            expect(toast.info).not.toHaveBeenCalled();
        }

        it('defaults to the first version the runtimes endpoint lists, which is the newest', async () => {
            mockApi(getK8sResourceLimitsApiV1K8sLimitsGet).ok(
                createMockResourceLimits({
                    supported_runtimes: { python: { versions: ['3.14', '3.13', '3.12'], file_ext: 'py' } },
                }),
            );
            await runAndExpect('python', '3.14');
        });

        it('keeps a stored version that is still offered', async () => {
            storeSelection('python', '3.12');
            await runAndExpect('python', '3.12');
        });

        it('keeps the stored language and picks its newest version when the stored version was dropped', async () => {
            mockApi(getK8sResourceLimitsApiV1K8sLimitsGet).ok(
                createMockResourceLimits({
                    supported_runtimes: {
                        python: { versions: ['3.14', '3.13'], file_ext: 'py' },
                        go: { versions: ['1.27', '1.26'], file_ext: 'go' },
                    },
                }),
            );
            storeSelection('go', '1.22');
            await runAndExpect('go', '1.27');
        });

        it.each([
            ['1.0', 'a version the fallback lacks'],
            ['3.12', 'a version the fallback also offers'],
        ])(
            'falls back to the first language and its newest version when the stored language is gone (%s, %s)',
            async (version) => {
                storeSelection('cobol', version);
                await runAndExpect('python', '3.14');
            },
        );
    });

    describe('Saved script with a dropped version', () => {
        it('switches to the newest offered version before running or saving', async () => {
            mockApi(listSavedScriptsApiV1ScriptsGet).ok({
                scripts: [
                    {
                        script_id: 'old-1',
                        name: 'Old Script',
                        script: 'print(1)',
                        lang: 'python',
                        lang_version: '3.7',
                        description: null,
                        created_at: '2024-01-01T00:00:00Z',
                        updated_at: '2024-01-01T00:00:00Z',
                    },
                ],
            });

            await renderEditor();
            await waitForRuntimes();

            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByRole('button', { name: 'Show Saved Scripts' }));
            await user.click(await screen.findByTitle('Load Old Script (python 3.7)'));

            await waitFor(() => {
                expect(toast.info).toHaveBeenCalledWith(
                    'Version 3.7 of python is no longer available, switched to 3.14.',
                );
            });
            expect(screen.getByRole('button', { name: 'Select language and version' })).toHaveTextContent(
                'python 3.14',
            );

            await user.click(screen.getByRole('button', { name: /Run Script/i }));
            expect(mocks.mockExecutionState.execute).toHaveBeenCalledWith('print(1)', 'python', '3.14');

            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByTitle('Save current script'));
            await waitFor(() => {
                expect(vi.mocked(updateSavedScriptApiV1ScriptsScriptIdPut)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { script_id: 'old-1' },
                        body: expect.objectContaining({ lang: 'python', lang_version: '3.14' }),
                    }),
                );
            });
        });
    });

    describe('New script', () => {
        it('calls execution.reset and shows toast when New is clicked', async () => {
            await renderEditor();
            await waitForRuntimes();

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

        it('rejects a script longer than the API allows, with the spec rule in the toast', async () => {
            const input = createFileInput();
            await waitForRuntimes();
            const bigFile = new File(['x'.repeat(50_001)], 'large.py', { type: 'text/plain' });
            fireFileChange(input, bigFile);
            await waitFor(() => {
                expect(toast.error).toHaveBeenCalledWith('Script must be at most 50000 characters');
            });
            expect(toast.info).not.toHaveBeenCalledWith(expect.stringContaining('Loaded python script'));
        });

        it('rejects unsupported file extension with error toast', async () => {
            const input = createFileInput();
            await waitForRuntimes();
            const badFile = new File(['content'], 'data.csv', { type: 'text/csv' });
            fireFileChange(input, badFile);
            expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Unsupported file type'));
        });

        it('loads .py file content and shows info toast', async () => {
            const input = createFileInput();
            await waitForRuntimes();
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
            await waitForRuntimes();
            const exampleBtn = screen.getByTitle('Load an example script for the selected language');
            await user.click(exampleBtn);
            expect(toast.info).toHaveBeenCalledWith('Loaded example script for python.');
            expect(mocks.mockExecutionState.reset).toHaveBeenCalled();
        });

        it('shows warning when no example available', async () => {
            mockApi(getExampleScriptsApiV1ExampleScriptsGet).ok({ scripts: {} });
            await renderEditor();
            await waitForRuntimes();
            const exampleBtn = screen.getByTitle('Load an example script for the selected language');
            await user.click(exampleBtn);
            expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining('No example script available'));
        });
    });

    describe('Export script', () => {
        it('creates download with correct filename and extension', async () => {
            await renderEditor();
            await waitForRuntimes();

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

            await user.type(screen.getByLabelText('Name'), 'my_script');
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
            await waitForRuntimes();

            await user.type(screen.getByLabelText('Name'), 'Persisted');

            // Wait for debounced localStorage write (300ms)
            await vi.advanceTimersByTimeAsync(400);

            const stored = localStorage.getItem('scriptName');
            expect(stored).toContain('Persisted');
        });
    });
});
