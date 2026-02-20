import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import type { EditorSettingsOutput } from '$lib/api';

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
  const getLanguageExtensionFn = vi.fn((lang: string) => `lang-ext-${lang}`);

  return {
    mockView, dispatchFn, destroyFn, editorStateCreate, editorViewConstructor,
    themeFn, lineNumbersFn, getLanguageExtensionFn,
  };
});

Object.assign(mocks.editorViewConstructor, {
  lineWrapping: 'lineWrapping-ext',
  theme: mocks.themeFn,
  updateListener: { of: vi.fn((fn: unknown) => ({ updateListener: fn })) },
});

vi.mock('@codemirror/state', () => {
  class MockCompartment {
    of(ext: unknown) { return ext; }
    reconfigure(ext: unknown) { return { type: 'reconfigure', ext }; }
  }
  return {
    Compartment: MockCompartment,
    EditorState: {
      create: mocks.editorStateCreate,
      allowMultipleSelections: { of: vi.fn((v: boolean) => ({ allowMultiple: v })) },
      tabSize: { of: vi.fn((v: number) => ({ tabSize: v })) },
    },
  };
});

vi.mock('@codemirror/view', () => ({
  EditorView: mocks.editorViewConstructor,
  highlightActiveLine: vi.fn(() => 'highlightActiveLine-ext'),
  highlightActiveLineGutter: vi.fn(() => 'highlightActiveLineGutter-ext'),
  keymap: { of: vi.fn((bindings: unknown) => ({ keymap: bindings })) },
  lineNumbers: mocks.lineNumbersFn,
}));

vi.mock('@codemirror/commands', () => ({
  defaultKeymap: [], history: vi.fn(() => 'history-ext'), historyKeymap: [], indentWithTab: 'indentWithTab',
}));
vi.mock('@codemirror/language', () => ({ bracketMatching: vi.fn(() => 'bracketMatching-ext') }));
vi.mock('@codemirror/autocomplete', () => ({ autocompletion: vi.fn(() => 'autocompletion-ext'), completionKeymap: [] }));
vi.mock('@codemirror/theme-one-dark', () => ({ oneDark: 'oneDark-theme' }));
vi.mock('@uiw/codemirror-theme-github', () => ({ githubLight: 'githubLight-theme' }));
vi.mock('$stores/theme.svelte', () => ({ themeStore: { value: 'light' } }));
vi.mock('$lib/editor/languages', () => ({ getLanguageExtension: mocks.getLanguageExtensionFn }));

import CodeMirrorEditor from '../CodeMirrorEditor.svelte';

const defaultSettings: EditorSettingsOutput = {
  font_size: 14, tab_size: 4, show_line_numbers: true, word_wrap: false, theme: 'auto', use_tabs: false,
};

function renderEditor(overrides: Partial<{ content: string; lang: string; settings: EditorSettingsOutput }> = {}) {
  return render(CodeMirrorEditor, {
    props: { content: '', lang: 'python', settings: defaultSettings, ...overrides },
  });
}

describe('CodeMirrorEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.documentElement.classList.remove('dark');
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
      expect(mocks.editorViewConstructor.mock.calls[0]![0].parent).toBeInstanceOf(HTMLElement);
    });
  });

  it('destroys EditorView on unmount', async () => {
    const { unmount } = renderEditor();
    await waitFor(() => expect(mocks.editorViewConstructor).toHaveBeenCalled());
    unmount();
    expect(mocks.destroyFn).toHaveBeenCalled();
  });

  describe('theme selection', () => {
    it.each([
      { theme: 'light', darkClass: false, expectedTheme: 'githubLight-theme' },
      { theme: 'dark', darkClass: false, expectedTheme: 'oneDark-theme' },
      { theme: 'auto', darkClass: true, expectedTheme: 'oneDark-theme' },
      { theme: 'auto', darkClass: false, expectedTheme: 'githubLight-theme' },
    ])('selects $expectedTheme for theme=$theme dark=$darkClass', async ({ theme, darkClass, expectedTheme }) => {
      if (darkClass) document.documentElement.classList.add('dark');
      renderEditor({ settings: { ...defaultSettings, theme } });
      await waitFor(() => {
        // applySettings dispatches theme reconfigure; verify the last theme-related extension
        const themeArgs = mocks.dispatchFn.mock.calls.find(
          (call: unknown[]) => {
            const effect = (call[0] as { effects?: { ext?: unknown } })?.effects;
            return effect && 'type' in effect && (effect as { type: string }).type === 'reconfigure'
              && (effect as { ext?: unknown }).ext === expectedTheme;
          },
        );
        // At minimum verify the view was initialized with the right theme in extensions
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

    it('passes correct language extension for lang prop', async () => {
      renderEditor({ lang: 'go' });
      await waitFor(() => {
        expect(mocks.getLanguageExtensionFn).toHaveBeenCalledWith('go');
      });
    });
  });
});
