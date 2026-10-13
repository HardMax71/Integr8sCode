import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { setMode } from 'mode-watcher';
import { Theme, zEditorSettingsInput, type EditorSettingsOutput } from '#lib/api/index.ts';

const mocks = vi.hoisted(() => {
    const dispatchFn = vi.fn();
    const destroyFn = vi.fn();
    const mockView = {
        dispatch: dispatchFn,
        destroy: destroyFn,
        state: {
            doc: { length: 0, toString: () => '' },
        },
    };

    const editorStateCreate = vi.fn((config: { doc: string; extensions: unknown[] }) => ({
        doc: { toString: () => config.doc, length: config.doc.length },
        extensions: config.extensions,
    }));

    const editorViewConstructor = vi.fn(function (this: Record<string, unknown>, _opts: unknown) {
        Object.assign(this, mockView);
    });

    const themeFn = vi.fn((obj: unknown) => ({ theme: obj }));
    const lineNumbersFn = vi.fn(() => 'lineNumbers-ext');
    const loadLanguageFn = vi.fn(async (lang: string) => `lang-ext-${lang}`);
    const compartment = {
        of: vi.fn((ext: unknown) => ext),
        reconfigure: vi.fn((ext: unknown) => ({ type: 'reconfigure', ext })),
    };

    return {
        mockView,
        dispatchFn,
        destroyFn,
        editorStateCreate,
        editorViewConstructor,
        themeFn,
        lineNumbersFn,
        loadLanguageFn,
        compartment,
    };
});

Object.assign(mocks.editorViewConstructor, {
    lineWrapping: 'lineWrapping-ext',
    theme: mocks.themeFn,
    updateListener: { of: vi.fn((fn: unknown) => ({ updateListener: fn })) },
    cspNonce: { of: vi.fn((v: string) => ({ cspNonce: v })) },
});

vi.mock('@codemirror/state', () => ({
    Compartment: vi.fn(function () {
        return mocks.compartment;
    }),
    EditorState: {
        create: mocks.editorStateCreate,
        allowMultipleSelections: { of: vi.fn((v: boolean) => ({ allowMultiple: v })) },
        tabSize: { of: vi.fn((v: number) => ({ tabSize: v })) },
    },
}));

vi.mock('@codemirror/view', () => ({
    EditorView: mocks.editorViewConstructor,
    highlightActiveLine: vi.fn(() => 'highlightActiveLine-ext'),
    highlightActiveLineGutter: vi.fn(() => 'highlightActiveLineGutter-ext'),
    keymap: { of: vi.fn((bindings: unknown) => ({ keymap: bindings })) },
    lineNumbers: mocks.lineNumbersFn,
}));

vi.mock('@codemirror/commands', () => ({
    defaultKeymap: [],
    history: vi.fn(() => 'history-ext'),
    historyKeymap: [],
    indentWithTab: 'indentWithTab',
}));
vi.mock('@codemirror/language', () => ({ bracketMatching: vi.fn(() => 'bracketMatching-ext') }));
vi.mock('@codemirror/autocomplete', () => ({
    autocompletion: vi.fn(() => 'autocompletion-ext'),
    completionKeymap: [],
}));
vi.mock('@codemirror/theme-one-dark', () => ({ oneDark: 'oneDark-theme' }));
vi.mock('@uiw/codemirror-theme-github', () => ({ githubLight: 'githubLight-theme' }));
vi.mock('#lib/editor/languages.ts', () => ({ loadLanguage: mocks.loadLanguageFn }));

import CodeMirrorEditor from '#components/editor/CodeMirrorEditor.svelte';

const defaultSettings: EditorSettingsOutput = zEditorSettingsInput.parse({});

function renderEditor(overrides: Partial<{ content: string; lang: string; settings: EditorSettingsOutput }> = {}) {
    return render(CodeMirrorEditor, {
        props: { content: '', lang: 'python', settings: defaultSettings, ...overrides },
    });
}

describe('CodeMirrorEditor', () => {
    beforeEach(() => {
        setMode(Theme.LIGHT);
    });

    it('renders wrapper with h-full and w-full classes', () => {
        const { container } = renderEditor();
        const wrapper = container.querySelector('.editor-wrapper');
        expect(wrapper).toBeInTheDocument();
        expect(wrapper?.classList.contains('h-full')).toBe(true);
        expect(wrapper?.classList.contains('w-full')).toBe(true);
    });

    it('creates EditorState with initial content and attaches to container', async () => {
        renderEditor({ content: 'print("hi")' });
        await waitFor(() => {
            expect(mocks.editorStateCreate).toHaveBeenCalled();
            expect(mocks.editorStateCreate.mock.calls[0]![0].doc).toBe('print("hi")');
            expect(mocks.editorViewConstructor).toHaveBeenCalled();
            expect((mocks.editorViewConstructor.mock.calls[0]![0] as Record<string, unknown>).parent).toBeInstanceOf(
                HTMLElement,
            );
        });
    });

    it('gives CodeMirror the nonce from the csp-nonce meta tag for its <style> tag', async () => {
        const meta = Object.assign(document.createElement('meta'), { name: 'csp-nonce', content: 'abc123' });
        document.head.append(meta);
        try {
            renderEditor();
            await waitFor(() => expect(mocks.editorStateCreate).toHaveBeenCalled());
            expect(mocks.editorStateCreate.mock.calls[0]![0].extensions).toContainEqual({ cspNonce: 'abc123' });
        } finally {
            meta.remove();
        }
    });

    it('puts content replaced from outside into the editor', async () => {
        const { rerender } = renderEditor();
        await waitFor(() => expect(mocks.editorViewConstructor).toHaveBeenCalled());
        await rerender({ content: 'print(1)' });
        expect(mocks.dispatchFn).toHaveBeenCalledWith(
            expect.objectContaining({ changes: { from: 0, to: 0, insert: 'print(1)' } }),
        );
    });

    it('destroys EditorView on unmount', async () => {
        const { unmount } = renderEditor();
        await waitFor(() => expect(mocks.editorViewConstructor).toHaveBeenCalled());
        unmount();
        expect(mocks.destroyFn).toHaveBeenCalled();
    });

    describe('theme selection', () => {
        it.each([
            { theme: Theme.LIGHT, expectedTheme: 'githubLight-theme' },
            { theme: Theme.DARK, expectedTheme: 'oneDark-theme' },
        ])('selects $expectedTheme for the $theme theme', async ({ theme, expectedTheme }) => {
            setMode(theme);
            renderEditor();
            await waitFor(() => {
                expect(mocks.editorStateCreate).toHaveBeenCalled();
                const extensions = mocks.editorStateCreate.mock.calls[0]![0].extensions;
                expect(extensions).toContain(expectedTheme);
            });
        });
    });

    describe('settings reconfiguration', () => {
        it('dispatches font size reconfigure with correct pixel value', async () => {
            renderEditor({ settings: { ...defaultSettings, font_size: 18 } });
            await waitFor(() => {
                expect(mocks.themeFn).toHaveBeenCalledWith(
                    expect.objectContaining({ '.cm-content': { fontSize: '18px' } }),
                );
            });
        });

        it('dispatches line numbers reconfigure based on setting', async () => {
            renderEditor({ settings: { ...defaultSettings, show_line_numbers: true } });
            await waitFor(() => {
                expect(mocks.lineNumbersFn).toHaveBeenCalled();
            });
        });

        it('loads the mode for the lang prop and puts it into the editor', async () => {
            renderEditor({ lang: 'go' });
            await waitFor(() => {
                expect(mocks.dispatchFn).toHaveBeenCalledWith({ effects: { type: 'reconfigure', ext: 'lang-ext-go' } });
            });
            expect(mocks.loadLanguageFn).toHaveBeenCalledWith('go');
        });

        it('keeps the newer language when an older load finishes last', async () => {
            const python = Promise.withResolvers<string>();
            mocks.loadLanguageFn.mockReturnValueOnce(python.promise);
            const { rerender } = renderEditor({ lang: 'python' });
            await rerender({ lang: 'go' });
            await waitFor(() => {
                expect(mocks.dispatchFn).toHaveBeenCalledWith({ effects: { type: 'reconfigure', ext: 'lang-ext-go' } });
            });
            python.resolve('lang-ext-python');
            await Promise.resolve();
            expect(mocks.dispatchFn).not.toHaveBeenCalledWith({
                effects: { type: 'reconfigure', ext: 'lang-ext-python' },
            });
        });
    });
});
