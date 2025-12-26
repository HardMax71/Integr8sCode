<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { Compartment, EditorState } from '@codemirror/state';
    import { EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from '@codemirror/view';
    import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
    import { bracketMatching } from '@codemirror/language';
    import { autocompletion, completionKeymap } from '@codemirror/autocomplete';
    import { oneDark } from '@codemirror/theme-one-dark';
    import { githubLight } from '@uiw/codemirror-theme-github';
    import { theme as appTheme } from '$stores/theme';
    import { getLanguageExtension } from '$lib/editor/languages';
    import type { EditorSettings } from '$lib/api';

    interface Props {
        content: string;
        lang: string;
        settings: EditorSettings;
        onchange?: (content: string) => void;
    }

    let { content = $bindable(''), lang, settings, onchange }: Props = $props();

    let container: HTMLElement;
    let view: EditorView | null = null;

    const themeCompartment = new Compartment();
    const fontSizeCompartment = new Compartment();
    const tabSizeCompartment = new Compartment();
    const lineNumbersCompartment = new Compartment();
    const lineWrappingCompartment = new Compartment();
    const languageCompartment = new Compartment();

    function getThemeExtension() {
        // Only use dark theme if explicitly set OR auto + dark mode active
        const useDark = settings.theme === 'one-dark' ||
            (settings.theme !== 'github' && document.documentElement.classList.contains('dark'));
        return useDark ? oneDark : githubLight;
    }

    function getStaticExtensions() {
        return [
            lineNumbersCompartment.of(settings.show_line_numbers ? lineNumbers() : []),
            highlightActiveLineGutter(),
            highlightActiveLine(),
            history(),
            bracketMatching(),
            autocompletion(),
            EditorState.allowMultipleSelections.of(true),
            tabSizeCompartment.of(EditorState.tabSize.of(settings.tab_size ?? 4)),
            keymap.of([...defaultKeymap, ...historyKeymap, ...completionKeymap, indentWithTab]),
            languageCompartment.of(getLanguageExtension(lang)),
            lineWrappingCompartment.of(settings.word_wrap ? EditorView.lineWrapping : []),
            fontSizeCompartment.of(EditorView.theme({ ".cm-content": { fontSize: `${settings.font_size ?? 14}px` } })),
            EditorView.theme({
                "&": { height: "100%", maxHeight: "100%" },
                ".cm-content": { minHeight: "100%" },
                ".cm-scroller": { overflow: "auto", maxHeight: "100%" }
            }),
            EditorView.updateListener.of(update => {
                if (update.docChanged) {
                    const newContent = update.state.doc.toString();
                    content = newContent;
                    onchange?.(newContent);
                }
            }),
        ];
    }

    function applySettings() {
        if (!view) return;
        view.dispatch({ effects: themeCompartment.reconfigure(getThemeExtension()) });
        view.dispatch({ effects: fontSizeCompartment.reconfigure(EditorView.theme({ ".cm-content": { fontSize: `${settings.font_size ?? 14}px` } })) });
        view.dispatch({ effects: tabSizeCompartment.reconfigure(EditorState.tabSize.of(settings.tab_size ?? 4)) });
        view.dispatch({ effects: lineNumbersCompartment.reconfigure(settings.show_line_numbers ? lineNumbers() : []) });
        view.dispatch({ effects: lineWrappingCompartment.reconfigure(settings.word_wrap ? EditorView.lineWrapping : []) });
    }

    let unsubscribeTheme: (() => void) | null = null;

    onMount(() => {
        if (!container) return;

        const startState = EditorState.create({
            doc: content,
            extensions: [...getStaticExtensions(), themeCompartment.of(getThemeExtension())]
        });

        view = new EditorView({ state: startState, parent: container });

        unsubscribeTheme = appTheme.subscribe(() => {
            if (view && (settings.theme === 'auto' || !settings.theme)) {
                view.dispatch({ effects: themeCompartment.reconfigure(getThemeExtension()) });
            }
        });
    });

    onDestroy(() => {
        view?.destroy();
        view = null;
        unsubscribeTheme?.();
    });

    $effect(() => {
        if (view) {
            view.dispatch({ effects: languageCompartment.reconfigure(getLanguageExtension(lang)) });
        }
    });

    $effect(() => {
        void settings;
        applySettings();
    });

    export function setContent(newContent: string) {
        if (!view) return;
        view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: newContent },
            selection: { anchor: 0 }
        });
    }

    export function getView(): EditorView | null {
        return view;
    }
</script>

<div bind:this={container} class="editor-wrapper h-full w-full"></div>
