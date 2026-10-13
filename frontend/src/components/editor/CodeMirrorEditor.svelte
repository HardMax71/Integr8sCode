<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { Compartment, EditorState } from '@codemirror/state';
    import { EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from '@codemirror/view';
    import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
    import { bracketMatching } from '@codemirror/language';
    import { autocompletion, completionKeymap } from '@codemirror/autocomplete';
    import { oneDark } from '@codemirror/theme-one-dark';
    import { githubLight } from '@uiw/codemirror-theme-github';
    import { mode } from 'mode-watcher';
    import { loadLanguage } from '#lib/editor/languages.ts';
    import type { EditorSettingsOutput } from '#lib/api/index.ts';

    interface Props {
        content: string;
        lang: string;
        settings: EditorSettingsOutput;
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
        return mode.current === 'dark' ? oneDark : githubLight;
    }

    function getStaticExtensions() {
        return [
            EditorView.cspNonce.of(document.querySelector('meta[name="csp-nonce"]')?.getAttribute('content') ?? ''),
            lineNumbersCompartment.of(settings.show_line_numbers ? lineNumbers() : []),
            highlightActiveLineGutter(),
            highlightActiveLine(),
            history(),
            bracketMatching(),
            autocompletion(),
            EditorState.allowMultipleSelections.of(true),
            tabSizeCompartment.of(EditorState.tabSize.of(settings.tab_size)),
            keymap.of([...defaultKeymap, ...historyKeymap, ...completionKeymap, indentWithTab]),
            languageCompartment.of([]),
            lineWrappingCompartment.of(settings.word_wrap ? EditorView.lineWrapping : []),
            fontSizeCompartment.of(EditorView.theme({ '.cm-content': { fontSize: `${settings.font_size}px` } })),
            EditorView.theme({
                '&': { height: '100%', maxHeight: '100%' },
                '.cm-content': { minHeight: '100%' },
                '.cm-scroller': { overflow: 'auto', maxHeight: '100%' },
            }),
            EditorView.updateListener.of((update) => {
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
        view.dispatch({
            effects: fontSizeCompartment.reconfigure(
                EditorView.theme({ '.cm-content': { fontSize: `${settings.font_size}px` } }),
            ),
        });
        view.dispatch({ effects: tabSizeCompartment.reconfigure(EditorState.tabSize.of(settings.tab_size)) });
        view.dispatch({ effects: lineNumbersCompartment.reconfigure(settings.show_line_numbers ? lineNumbers() : []) });
        view.dispatch({
            effects: lineWrappingCompartment.reconfigure(settings.word_wrap ? EditorView.lineWrapping : []),
        });
    }

    onMount(() => {
        if (!container) return;

        const startState = EditorState.create({
            doc: content,
            extensions: [...getStaticExtensions(), themeCompartment.of(getThemeExtension())],
        });

        view = new EditorView({ state: startState, parent: container });
    });

    onDestroy(() => {
        view?.destroy();
        view = null;
    });

    // React to app theme changes
    $effect(() => {
        void mode.current;
        if (view) {
            view.dispatch({ effects: themeCompartment.reconfigure(getThemeExtension()) });
        }
    });

    // A language switched while its mode still loads drops the older load
    $effect(() => {
        let current = true;
        void loadLanguage(lang).then((extension) => {
            if (current) view?.dispatch({ effects: languageCompartment.reconfigure(extension) });
        });
        return () => {
            current = false;
        };
    });

    $effect(() => {
        void settings;
        applySettings();
    });

    // A script replaced from outside (opened, uploaded, an example) goes into the editor
    $effect(() => {
        if (view && content !== view.state.doc.toString()) {
            view.dispatch({
                changes: { from: 0, to: view.state.doc.length, insert: content },
                selection: { anchor: 0 },
            });
        }
    });
</script>

<div bind:this={container} class="editor-wrapper h-full w-full"></div>
