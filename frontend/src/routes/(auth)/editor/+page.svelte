<script lang="ts">
    import { fade, slide } from 'svelte/transition';
    import { createQuery } from '@tanstack/svelte-query';
    import { CirclePlay, Settings, Lightbulb } from '@lucide/svelte';
    import {
        getK8sResourceLimitsApiV1K8sLimitsGetOptions,
        getUserSettingsApiV1UserSettingsGetOptions,
        zEditorSettingsInput,
    } from '#lib/api/index.ts';
    import { createExecutionState, draft, executionContext, pickRuntime } from '#lib/editor/index.ts';
    import { toast } from 'svelte-sonner';
    import {
        CodeMirrorEditor,
        OutputPanel,
        LanguageSelect,
        ResourceLimits,
        EditorToolbar,
        ScriptActions,
        SavedScripts,
        LoadExample,
    } from '#components/editor/index.ts';

    const DEFAULT_EDITOR_SETTINGS = zEditorSettingsInput.parse({});

    const limits = createQuery(() => getK8sResourceLimitsApiV1K8sLimitsGetOptions());
    const settings = createQuery(() => getUserSettingsApiV1UserSettingsGetOptions());
    const runtimesAvailable = $derived(Object.keys(limits.data?.supported_runtimes ?? {}).length > 0);
    const execution = executionContext.set(createExecutionState());

    let showOptions = $state(false);

    const runtime = $derived(pickRuntime(draft.current, limits.data?.supported_runtimes ?? {}));

    function run(): void {
        const { lang, lang_version } = runtime;
        if (lang === draft.current.lang && lang_version !== draft.current.lang_version) {
            toast.info(
                `Version ${draft.current.lang_version} of ${lang} is no longer available, switched to ${lang_version}.`,
            );
        }
        draft.current.lang = lang;
        draft.current.lang_version = lang_version;
        void execution.execute(draft.current.script, lang, lang_version);
    }
</script>

<svelte:head>
    <title>Code Editor - Integr8sCode</title>
    <meta
        name="description"
        content="Online code editor with syntax highlighting, multi-language support, and real-time compilation. Write and test your code instantly in the browser"
    />
</svelte:head>

<div class="editor-grid-container space-y-4 md:space-y-0 md:gap-6" in:fade={{ duration: 300 }}>
    <div class="editor-header flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h2 class="sm:text-2xl whitespace-nowrap">Code Editor</h2>
        <ResourceLimits />
    </div>

    <div class="editor-main-code flex flex-col rounded-lg overflow-hidden shadow-md border">
        <EditorToolbar />
        <div class="editor-wrapper h-full w-full relative">
            <CodeMirrorEditor
                bind:content={draft.current.script}
                lang={runtime.lang}
                settings={settings.data?.editor ?? DEFAULT_EDITOR_SETTINGS}
            />
            {#if draft.current.script.trim() === ''}
                <div
                    class="absolute inset-0 flex flex-col items-center justify-center p-4 text-center pointer-events-none"
                >
                    <h3 class="text-lg font-semibold">Editor is Empty</h3>
                    <p class="text-sm text-fg-muted mt-1 mb-4">
                        Start typing, upload a file, or use an example to begin.
                    </p>
                    <LoadExample class="btn btn-primary gap-2 pointer-events-auto">
                        <Lightbulb class="size-4" />
                        <span>Start with an Example</span>
                    </LoadExample>
                </div>
            {/if}
        </div>
    </div>

    <div class="editor-main-output">
        <OutputPanel phase={execution.phase} result={execution.result} error={execution.error} />
    </div>

    <div class="editor-controls">
        <div class="flex flex-col gap-y-3">
            <div class="flex items-center gap-x-2 flex-wrap gap-y-2">
                <LanguageSelect />
                <button
                    type="button"
                    class="btn btn-primary btn-sm flex-grow sm:flex-grow-0 min-w-32.5"
                    onclick={run}
                    disabled={execution.isExecuting || !runtimesAvailable}
                >
                    <CirclePlay class="size-5" />
                    <span class="ml-1.5">{execution.isExecuting ? 'Executing...' : 'Run Script'}</span>
                </button>
                <button
                    type="button"
                    class="btn btn-secondary-outline btn-sm btn-icon ml-auto sm:ml-2"
                    onclick={() => (showOptions = !showOptions)}
                    aria-expanded={showOptions}
                    title={showOptions ? 'Hide Options' : 'Show Options'}
                >
                    <span class="sr-only">Toggle Script Options</span>
                    <div class="transition-transform duration-300 ease-out-expo" class:rotate-90={showOptions}>
                        <Settings class="size-5" />
                    </div>
                </button>
            </div>

            {#if showOptions}
                <div
                    class="p-4 bg-surface border rounded-lg flex gap-x-4"
                    transition:slide={{ duration: 300, easing: (t) => 1 - Math.pow(1 - t, 3) }}
                >
                    <div class="w-1/2">
                        <ScriptActions />
                    </div>
                    <div class="border-l"></div>
                    <div class="w-1/2">
                        <SavedScripts />
                    </div>
                </div>
            {/if}
        </div>
    </div>
</div>
