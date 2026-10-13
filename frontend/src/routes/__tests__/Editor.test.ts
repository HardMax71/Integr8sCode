import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import * as z from 'zod/mini';
import { user, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { fakeResourceLimits, fakeSavedScriptResponse, fakeUserSettings } from '#lib/api/@faker-js/faker.gen.ts';
import { toast } from 'svelte-sonner';
import Editor from '#routes/(auth)/editor/+page.svelte';
import { draft } from '#lib/editor/draft.svelte.ts';

import {
    getK8sResourceLimitsApiV1K8sLimitsGet,
    getExampleScriptsApiV1ExampleScriptsGet,
    listSavedScriptsApiV1ScriptsGet,
    createSavedScriptApiV1ScriptsPost,
    updateSavedScriptApiV1ScriptsScriptIdPut,
    deleteSavedScriptApiV1ScriptsScriptIdDelete,
    getUserSettingsApiV1UserSettingsGet,
    zExecutionRequest,
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
}));

vi.mock('#lib/editor/index.ts', async (importOriginal) => ({
    ...(await importOriginal<typeof import('#lib/editor/index.ts')>()),
    createExecutionState: () => mocks.mockExecutionState,
}));

// Run Script stays disabled until the runtimes have loaded
async function waitForRuntimes(): Promise<void> {
    await waitFor(() => expect(screen.getByRole('button', { name: /Run Script/i })).toBeEnabled());
}

async function openSavedScripts(): Promise<void> {
    renderWithQueryClient(Editor);
    await waitForRuntimes();
    await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
}

async function runAndExpect(lang: string, version: string, notice?: string): Promise<void> {
    renderWithQueryClient(Editor);
    await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Select language and version' })).toHaveTextContent(
            `${lang} ${version}`,
        );
    });
    await user.click(screen.getByRole('button', { name: /Run Script/i }));
    expect(mocks.mockExecutionState.execute).toHaveBeenCalledWith(expect.any(String), lang, version);
    if (notice) expect(toast.info).toHaveBeenCalledWith(notice);
    else expect(toast.info).not.toHaveBeenCalled();
}

async function openFileInput(): Promise<HTMLInputElement> {
    const { container } = renderWithQueryClient(Editor);
    await waitForRuntimes();
    await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
    return container.querySelector('input[type="file"]') as HTMLInputElement;
}

describe('Editor', () => {
    beforeEach(() => {
        // While storage is empty, the page's field writes change PersistedState's initial value in place
        draft.current = { script_id: null, name: '', ...zExecutionRequest.parse({ script: '' }) };
        vi.stubGlobal('confirm', mocks.mockConfirm);
        mocks.mockExecutionState.phase = 'idle';
        mocks.mockExecutionState.isExecuting = false;
        mocks.mockExecutionState.result = null;
        mocks.mockExecutionState.error = null;

        mockApi(getK8sResourceLimitsApiV1K8sLimitsGet).ok({
            ...fakeResourceLimits(),
            supported_runtimes: { python: { versions: ['3.14', '3.13', '3.12', '3.11'], file_ext: 'py' } },
        });
        mockApi(getExampleScriptsApiV1ExampleScriptsGet).ok({ scripts: { python: 'print("Hello")' } });
        mockApi(listSavedScriptsApiV1ScriptsGet).ok({ scripts: [] });
        mockApi(getUserSettingsApiV1UserSettingsGet).ok(fakeUserSettings());
        mockApi(createSavedScriptApiV1ScriptsPost).ok({ ...fakeSavedScriptResponse(), script_id: 'new-1' });
        mockApi(updateSavedScriptApiV1ScriptsScriptIdPut).ok(fakeSavedScriptResponse());
        mockApi(deleteSavedScriptApiV1ScriptsScriptIdDelete).ok();
    });

    describe('Mount', () => {
        it('loads the limits, the examples and the user settings, and the saved scripts once the options open', async () => {
            renderWithQueryClient(Editor);
            await waitFor(() => {
                expect(vi.mocked(getK8sResourceLimitsApiV1K8sLimitsGet)).toHaveBeenCalled();
                expect(vi.mocked(getExampleScriptsApiV1ExampleScriptsGet)).toHaveBeenCalled();
                expect(vi.mocked(getUserSettingsApiV1UserSettingsGet)).toHaveBeenCalled();
            });
            expect(vi.mocked(listSavedScriptsApiV1ScriptsGet)).not.toHaveBeenCalled();

            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await waitFor(() => expect(vi.mocked(listSavedScriptsApiV1ScriptsGet)).toHaveBeenCalled());
        });

        it('renders page heading "Code Editor"', async () => {
            renderWithQueryClient(Editor);
            await waitFor(() => {
                expect(screen.getByRole('heading', { name: 'Code Editor' })).toBeInTheDocument();
            });
        });

        it('sets the page title', async () => {
            renderWithQueryClient(Editor);
            await waitFor(() => expect(document.title).toBe('Code Editor - Integr8sCode'));
        });
    });

    describe('Save script', () => {
        it('creates new script via POST API when Save is clicked', async () => {
            renderWithQueryClient(Editor);
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
            await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Script saved successfully.'));
        });

        it('falls back to create when update returns 404', async () => {
            mockApi(listSavedScriptsApiV1ScriptsGet).ok({
                scripts: [
                    {
                        ...fakeSavedScriptResponse(),
                        script_id: 'script-99',
                        name: 'Existing Script',
                        lang: 'python',
                        lang_version: '3.11',
                    },
                ],
            });
            vi.mocked(updateSavedScriptApiV1ScriptsScriptIdPut).mockRejectedValue({ status: 404, detail: 'Not found' });
            mockApi(createSavedScriptApiV1ScriptsPost).ok({ ...fakeSavedScriptResponse(), script_id: 'fallback-1' });

            renderWithQueryClient(Editor);
            await waitForRuntimes();

            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByRole('button', { name: 'Show Saved Scripts' }));
            await waitFor(() => {
                expect(screen.getByTitle(/Load Existing Script/)).toBeInTheDocument();
            });
            await user.click(screen.getByTitle(/Load Existing Script/));
            expect(toast.info).toHaveBeenCalledWith('Loaded script: Existing Script');

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
            await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Script saved successfully.'));
        });
    });

    describe('Delete script', () => {
        it('calls confirm and delete API when delete button is clicked', async () => {
            mocks.mockConfirm.mockReturnValue(true);
            mockApi(listSavedScriptsApiV1ScriptsGet).ok({
                scripts: [{ ...fakeSavedScriptResponse(), script_id: 'script-99', name: 'My Script' }],
            });

            renderWithQueryClient(Editor);
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
            await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Script deleted successfully.'));
        });
    });

    describe('Saved scripts list', () => {
        it('says so when there are none, and reloads the list each time it opens', async () => {
            await openSavedScripts();
            await waitFor(() => expect(vi.mocked(listSavedScriptsApiV1ScriptsGet)).toHaveBeenCalledTimes(1));
            await user.click(screen.getByRole('button', { name: 'Show Saved Scripts' }));
            expect(await screen.findByText('No saved scripts yet.')).toBeInTheDocument();
            await waitFor(() => expect(vi.mocked(listSavedScriptsApiV1ScriptsGet)).toHaveBeenCalledTimes(2));
        });

        it('keeps a script when its deletion is cancelled', async () => {
            mocks.mockConfirm.mockReturnValue(false);
            mockApi(listSavedScriptsApiV1ScriptsGet).ok({
                scripts: [{ ...fakeSavedScriptResponse(), name: 'Keep Me' }],
            });
            await openSavedScripts();
            await user.click(screen.getByRole('button', { name: 'Show Saved Scripts' }));
            await user.click(await screen.findByTitle('Delete Keep Me'));
            expect(vi.mocked(deleteSavedScriptApiV1ScriptsScriptIdDelete)).not.toHaveBeenCalled();
        });
    });

    describe('Execution', () => {
        it('calls execution.execute with script, lang, and version when Run Script is clicked', async () => {
            renderWithQueryClient(Editor);
            await waitForRuntimes();

            await user.click(screen.getByRole('button', { name: /Run Script/i }));
            expect(mocks.mockExecutionState.execute).toHaveBeenCalledWith(expect.any(String), 'python', '3.14');
        });
    });

    describe('Initial language and version', () => {
        it('defaults to the first version the runtimes endpoint lists, which is the newest', async () => {
            mockApi(getK8sResourceLimitsApiV1K8sLimitsGet).ok({
                ...fakeResourceLimits(),
                supported_runtimes: { python: { versions: ['3.14', '3.13', '3.12'], file_ext: 'py' } },
            });
            await runAndExpect('python', '3.14');
        });

        it('keeps a stored version that is still offered', async () => {
            draft.current = { ...draft.current, lang: 'python', lang_version: '3.12' };
            await runAndExpect('python', '3.12');
        });

        it('keeps the stored language and picks its newest version when the stored version was dropped', async () => {
            mockApi(getK8sResourceLimitsApiV1K8sLimitsGet).ok({
                ...fakeResourceLimits(),
                supported_runtimes: {
                    python: { versions: ['3.14', '3.13'], file_ext: 'py' },
                    go: { versions: ['1.27', '1.26'], file_ext: 'go' },
                },
            });
            draft.current = { ...draft.current, lang: 'go', lang_version: '1.22' };
            await runAndExpect('go', '1.27', 'Version 1.22 of go is no longer available, switched to 1.27.');
        });

        it.each([
            ['1.0', 'a version the fallback lacks'],
            ['3.12', 'a version the fallback also offers'],
        ])(
            'falls back to the first language and its newest version when the stored language is gone (%s, %s)',
            async (version) => {
                draft.current = { ...draft.current, lang: 'cobol', lang_version: version };
                await runAndExpect('python', '3.14');
            },
        );
    });

    describe('Saved script with a dropped version', () => {
        it('switches to the newest offered version before running or saving', async () => {
            mockApi(listSavedScriptsApiV1ScriptsGet).ok({
                scripts: [
                    {
                        ...fakeSavedScriptResponse(),
                        script_id: 'old-1',
                        name: 'Old Script',
                        script: 'print(1)',
                        lang: 'python',
                        lang_version: '3.7',
                    },
                ],
            });

            renderWithQueryClient(Editor);
            await waitForRuntimes();

            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByRole('button', { name: 'Show Saved Scripts' }));
            await user.click(await screen.findByTitle('Load Old Script (python 3.7)'));

            await waitFor(() => {
                expect(screen.getByRole('button', { name: 'Select language and version' })).toHaveTextContent(
                    'python 3.14',
                );
            });

            await user.click(screen.getByRole('button', { name: /Run Script/i }));
            expect(toast.info).toHaveBeenCalledWith('Version 3.7 of python is no longer available, switched to 3.14.');
            expect(mocks.mockExecutionState.execute).toHaveBeenCalledWith('print(1)', 'python', '3.14');

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
            renderWithQueryClient(Editor);
            await waitForRuntimes();

            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByRole('button', { name: 'New' }));
            expect(mocks.mockExecutionState.reset).toHaveBeenCalled();
            expect(toast.info).toHaveBeenCalledWith('New script started.');
        });
    });

    describe('File upload', () => {
        it('rejects a script longer than the API allows, with the spec rule in the toast', async () => {
            const { maxLength } = z.toJSONSchema(zExecutionRequest.shape.script);
            const input = await openFileInput();
            const bigFile = new File(['x'.repeat(maxLength! + 1)], 'large.py', { type: 'text/plain' });
            await user.upload(input, bigFile);
            await waitFor(() => {
                expect(toast.error).toHaveBeenCalledWith(`Script must be at most ${maxLength} characters`);
            });
            expect(toast.info).not.toHaveBeenCalledWith(expect.stringContaining('Loaded python script'));
        });

        it('rejects unsupported file extension with error toast', async () => {
            const input = await openFileInput();
            const badFile = new File(['content'], 'data.csv', { type: 'text/csv' });
            await userEvent.setup({ applyAccept: false, delay: null }).upload(input, badFile);
            expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('Unsupported file type'));
        });

        it('loads .py file content and shows info toast', async () => {
            const input = await openFileInput();
            const pyFile = new File(['print("loaded")'], 'test_script.py', { type: 'text/plain' });
            await user.upload(input, pyFile);
            await waitFor(() => {
                expect(toast.info).toHaveBeenCalledWith(
                    expect.stringContaining('Loaded python script from test_script.py'),
                );
            });
        });
    });

    describe('Example script loading', () => {
        it('loads example for selected language', async () => {
            renderWithQueryClient(Editor);
            await waitForRuntimes();
            const exampleBtn = screen.getByRole('button', { name: 'Example' });
            await user.click(exampleBtn);
            expect(toast.info).toHaveBeenCalledWith('Loaded example script for python.');
            expect(draft.current.script).toBe('print("Hello")');
            expect(mocks.mockExecutionState.reset).toHaveBeenCalled();
        });

        it('shows warning when no example available', async () => {
            mockApi(getExampleScriptsApiV1ExampleScriptsGet).ok({ scripts: {} });
            renderWithQueryClient(Editor);
            await waitForRuntimes();
            const exampleBtn = screen.getByRole('button', { name: 'Example' });
            await user.click(exampleBtn);
            expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining('No example script available'));
        });
    });

    describe('Export script', () => {
        it('creates download with correct filename and extension', async () => {
            renderWithQueryClient(Editor);
            await waitForRuntimes();

            const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
            const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url');
            const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});

            await user.type(screen.getByLabelText('Name'), 'my_script');
            await user.click(screen.getByRole('button', { name: 'Toggle Script Options' }));
            await user.click(screen.getByTitle('Download current script'));

            expect(createObjectURL).toHaveBeenCalled();
            expect(click.mock.contexts[0]).toHaveProperty('download', 'my_script.py');
            expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url');
        });
    });

    describe('localStorage persistence', () => {
        it('keeps the open script in localStorage', async () => {
            renderWithQueryClient(Editor);
            await waitForRuntimes();

            await user.type(screen.getByLabelText('Name'), 'Persisted');

            expect(JSON.parse(localStorage.getItem('editorDraft') ?? '{}')).toMatchObject({ name: 'Persisted' });
        });
    });
});
