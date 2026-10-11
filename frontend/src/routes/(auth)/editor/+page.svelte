<script lang="ts">
    import { untrack } from 'svelte';
    import { fade, slide } from 'svelte/transition';
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import { authStore } from '#stores/auth.svelte.ts';
    import {
        getK8sResourceLimitsApiV1K8sLimitsGetOptions,
        getExampleScriptsApiV1ExampleScriptsGetOptions,
        getUserSettingsApiV1UserSettingsGetOptions,
        listSavedScriptsApiV1ScriptsGetOptions,
        listSavedScriptsApiV1ScriptsGetQueryKey,
        createSavedScriptApiV1ScriptsPostMutation,
        updateSavedScriptApiV1ScriptsScriptIdPutMutation,
        deleteSavedScriptApiV1ScriptsScriptIdDeleteMutation,
        zEditorSettingsInput,
        type SavedScriptResponse,
    } from '#lib/api/index.ts';
    import { ApiError } from '#lib/api-error.ts';
    import { toast } from 'svelte-sonner';
    import Spinner from '#components/Spinner.svelte';
    import { CirclePlay, Settings, Lightbulb } from '@lucide/svelte';
    import { createExecutionState, newestVersion } from '#lib/editor/index.ts';
    import {
        CodeMirrorEditor,
        OutputPanel,
        LanguageSelect,
        ResourceLimits as ResourceLimitsPanel,
        EditorToolbar,
        ScriptActions,
        SavedScripts,
    } from '#components/editor/index.ts';

    function loadFromStorage<T>(key: string, defaultValue: T): T {
        if (typeof localStorage === 'undefined') return defaultValue;
        const stored = localStorage.getItem(key);
        if (!stored) return defaultValue;
        try {
            return JSON.parse(stored) as T;
        } catch {
            localStorage.removeItem(key);
            return defaultValue;
        }
    }

    // Local persistent state
    let script = $state(loadFromStorage('script', "# Welcome to Integr8sCode!\n\nprint('Hello, Kubernetes!')"));
    let scriptName = $state(loadFromStorage('scriptName', ''));
    let currentScriptId = $state<string | null>(loadFromStorage('currentScriptId', null));
    let selectedLang = $state(loadFromStorage('selectedLang', 'python'));
    let selectedVersion = $state(loadFromStorage('selectedVersion', ''));

    // Persist to localStorage (debounced to avoid serializing on every keystroke)
    $effect(() => {
        const snapshot = { script, scriptName, currentScriptId, selectedLang, selectedVersion };
        const timer = setTimeout(() => {
            try {
                for (const [key, value] of Object.entries(snapshot)) {
                    localStorage.setItem(key, JSON.stringify(value));
                }
            } catch {
                /* Quota exceeded or private browsing */
            }
        }, 300);
        return () => clearTimeout(timer);
    });

    // State
    let prevAuth = false;
    let authenticated = $derived(authStore.isAuthenticated ?? false);
    let showOptions = $state(false);
    let fileInput: HTMLInputElement;
    let editorRef: CodeMirrorEditor;
    let nameEditedByUser = false;

    const DEFAULT_EDITOR_SETTINGS = zEditorSettingsInput.parse({});

    const queryClient = useQueryClient();
    const limitsQuery = createQuery(() => getK8sResourceLimitsApiV1K8sLimitsGetOptions());
    const examplesQuery = createQuery(() => getExampleScriptsApiV1ExampleScriptsGetOptions());
    const settingsQuery = createQuery(() => ({
        ...getUserSettingsApiV1UserSettingsGetOptions(),
        enabled: authenticated,
    }));
    const scriptsQuery = createQuery(() => ({ ...listSavedScriptsApiV1ScriptsGetOptions(), enabled: authenticated }));

    let k8sLimits = $derived(limitsQuery.data ?? null);
    let supportedRuntimes = $derived(k8sLimits?.supported_runtimes ?? {});
    let exampleScripts = $derived(examplesQuery.data?.scripts ?? {});
    let savedScripts = $derived(scriptsQuery.data?.scripts ?? []);
    let editorSettings = $derived(settingsQuery.data?.editor ?? DEFAULT_EDITOR_SETTINGS);

    const execution = createExecutionState();
    const runtimesAvailable = $derived(Object.keys(supportedRuntimes).length > 0);
    const acceptedFileExts = $derived(
        Object.values(supportedRuntimes)
            .map((i) => `.${i.file_ext}`)
            .join(',') || '.txt',
    );

    // Fall back to a supported language once the runtimes load; .pre, so LanguageSelect never sees the old one
    $effect.pre(() => {
        const runtimes = limitsQuery.data?.supported_runtimes;
        if (!runtimes) return;
        untrack(() => {
            const lang = selectedLang in runtimes ? selectedLang : Object.keys(runtimes)[0];
            const versions = lang ? (runtimes[lang]?.versions ?? []) : [];
            if (lang && (lang !== selectedLang || !versions.includes(selectedVersion))) {
                selectedLang = lang;
                selectedVersion = newestVersion(versions) ?? '';
            }
        });
    });

    $effect(() => {
        if (nameEditedByUser && typeof window !== 'undefined' && currentScriptId && savedScripts.length > 0) {
            const saved = savedScripts.find((s) => s.script_id === currentScriptId);
            if (saved && saved.name !== scriptName) {
                currentScriptId = null;
                toast.info('Script name changed. Next save will create a new script.');
            }
            nameEditedByUser = false;
        }
    });

    // Signing out drops the saved scripts with every other query, so forget which one is open
    $effect(() => {
        const isAuth = authenticated;
        if (prevAuth && !isAuth) {
            currentScriptId = null;
            scriptName = '';
        }
        prevAuth = isAuth;
    });

    function refreshScripts(): Promise<void> {
        return queryClient.invalidateQueries({ queryKey: listSavedScriptsApiV1ScriptsGetQueryKey() });
    }

    const createScript = createMutation(() => ({
        ...createSavedScriptApiV1ScriptsPostMutation(),
        onSuccess: (data) => {
            currentScriptId = data.script_id;
            toast.success('Script saved successfully.');
            return refreshScripts();
        },
    }));

    const updateScript = createMutation(() => ({
        ...updateSavedScriptApiV1ScriptsScriptIdPutMutation(),
        onSuccess: () => {
            toast.success('Script updated successfully.');
            return refreshScripts();
        },
    }));

    const deleteScriptMutation = createMutation(() => ({
        ...deleteSavedScriptApiV1ScriptsScriptIdDeleteMutation(),
        onSuccess: (_data, { path }) => {
            toast.success('Script deleted successfully.');
            if (currentScriptId === path.script_id) newScript();
            return refreshScripts();
        },
    }));

    function loadScript(s: SavedScriptResponse) {
        script = s.script;
        scriptName = s.name;
        currentScriptId = s.script_id;
        selectedLang = s.lang;
        selectedVersion = s.lang_version;
        editorRef?.setContent(s.script);
        execution.reset();
        toast.info(`Loaded script: ${s.name}`);
        showOptions = false;
    }

    function saveScript() {
        if (!authenticated) {
            toast.warning('Please log in to save scripts.');
            return;
        }
        if (!scriptName.trim()) {
            toast.warning('Please provide a name for your script.');
            return;
        }

        const body = { name: scriptName, script, lang: selectedLang, lang_version: selectedVersion };
        if (!currentScriptId) {
            createScript.mutate({ body });
            return;
        }
        updateScript.mutate(
            { path: { script_id: currentScriptId }, body },
            {
                onError: (err) => {
                    // Deleted elsewhere, so save it as a new script
                    if (err instanceof ApiError && err.status === 404) {
                        currentScriptId = null;
                        createScript.mutate({ body });
                    }
                },
            },
        );
    }

    function deleteScript(id: string) {
        const s = savedScripts.find((x) => x.script_id === id);
        if (
            !confirm(
                s ? `Are you sure you want to delete "${s.name}"?` : 'Are you sure you want to delete this script?',
            )
        )
            return;
        deleteScriptMutation.mutate({ path: { script_id: id } });
    }

    function newScript() {
        script = '';
        scriptName = '';
        currentScriptId = null;
        editorRef?.setContent('');
        execution.reset();
        toast.info('New script started.');
    }

    function exportScript() {
        const blob = new Blob([script], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const ext = supportedRuntimes[selectedLang]?.file_ext || 'txt';
        let filename = scriptName.trim() || `script.${ext}`;
        if (!filename.toLowerCase().endsWith(`.${ext}`)) filename = filename.replace(/\.[^.]+$/, '') + `.${ext}`;
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    const MAX_FILE_SIZE = 1024 * 1024; // 1MB

    function handleFileUpload(event: Event) {
        const file = (event.target as HTMLInputElement).files?.[0];
        if (!file) return;

        if (file.size > MAX_FILE_SIZE) {
            toast.error('File too large. Maximum size is 1MB.');
            (event.target as HTMLInputElement).value = '';
            return;
        }

        const extToLang: Record<string, string> = {};
        for (const [lang, info] of Object.entries(supportedRuntimes)) extToLang[info.file_ext] = lang;

        const fileExt = file.name.split('.').pop()?.toLowerCase() || '';
        const detectedLang = extToLang[fileExt];

        if (!detectedLang) {
            toast.error(
                `Unsupported file type. Allowed: ${Object.values(supportedRuntimes)
                    .map((i) => `.${i.file_ext}`)
                    .join(', ')}`,
            );
            (event.target as HTMLInputElement).value = '';
            return;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            const text = e.target?.result as string;
            newScript();
            script = text;
            scriptName = file.name;
            selectedLang = detectedLang;
            const newest = newestVersion(supportedRuntimes[detectedLang]?.versions ?? []);
            if (newest) selectedVersion = newest;
            editorRef?.setContent(text);
            toast.info(`Loaded ${detectedLang} script from ${file.name}`);
        };
        reader.onerror = () => toast.error('Failed to read the selected file.');
        reader.readAsText(file);
        (event.target as HTMLInputElement).value = '';
    }

    function loadExampleScript() {
        const example = exampleScripts[selectedLang];
        if (!example) {
            toast.warning(`No example script available for ${selectedLang}.`);
            return;
        }

        const lines = example.split('\n');
        const firstLine = lines.find((l: string) => l.trim().length > 0);
        const indent = firstLine ? (firstLine.match(/^\s*/) ?? [''])[0] : '';
        const cleaned = lines
            .map((l: string) => (l.startsWith(indent) ? l.substring(indent.length) : l))
            .join('\n')
            .trim();

        script = cleaned;
        editorRef?.setContent(cleaned);
        execution.reset();
        toast.info(`Loaded example script for ${selectedLang}.`);
    }

    function handleExecute() {
        execution.execute(script, selectedLang, selectedVersion);
    }
</script>

<svelte:head>
    <title>Code Editor - Integr8sCode</title>
    <meta
        name="description"
        content="Online code editor with syntax highlighting, multi-language support, and real-time compilation. Write and test your code instantly in the browser"
    />
</svelte:head>

<input type="file" accept={acceptedFileExts} bind:this={fileInput} class="hidden" onchange={handleFileUpload} />

<div class="editor-grid-container space-y-4 md:space-y-0 md:gap-6" in:fade={{ duration: 300 }}>
    <div class="editor-header flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h2 class="text-xl sm:text-2xl font-semibold text-fg-default dark:text-dark-fg-default whitespace-nowrap">
            Code Editor
        </h2>
        <ResourceLimitsPanel limits={k8sLimits} lang={selectedLang} />
    </div>

    <div
        class="editor-main-code flex flex-col rounded-lg overflow-hidden shadow-md border border-border-default dark:border-dark-border-default"
    >
        <EditorToolbar
            name={scriptName}
            onchange={(n) => {
                scriptName = n;
                nameEditedByUser = true;
            }}
            onexample={loadExampleScript}
        />
        <div class="editor-wrapper h-full w-full relative">
            <CodeMirrorEditor
                bind:this={editorRef}
                bind:content={script}
                lang={selectedLang}
                settings={editorSettings}
            />
            {#if script.trim() === ''}
                <div
                    class="absolute inset-0 flex flex-col items-center justify-center p-4 text-center pointer-events-none"
                >
                    <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default">Editor is Empty</h3>
                    <p class="text-sm text-fg-muted dark:text-dark-fg-muted mt-1 mb-4">
                        Start typing, upload a file, or use an example to begin.
                    </p>
                    <button
                        type="button"
                        class="btn btn-primary inline-flex items-center space-x-2 pointer-events-auto"
                        onclick={loadExampleScript}
                    >
                        <Lightbulb class="w-4 h-4" />
                        <span>Start with an Example</span>
                    </button>
                </div>
            {/if}
        </div>
    </div>

    <div class="editor-main-output">
        <OutputPanel phase={execution.phase} result={execution.result} error={execution.error} />
    </div>

    <div class="editor-controls">
        <div class="flex flex-col space-y-3">
            <div class="flex items-center space-x-2 flex-wrap gap-y-2">
                <LanguageSelect
                    runtimes={supportedRuntimes}
                    lang={selectedLang}
                    version={selectedVersion}
                    onselect={(l, v) => {
                        selectedLang = l;
                        selectedVersion = v;
                    }}
                />
                <button
                    type="button"
                    class="btn btn-primary btn-sm flex-grow sm:flex-grow-0 min-w-[130px]"
                    onclick={handleExecute}
                    disabled={execution.isExecuting || !runtimesAvailable}
                >
                    <CirclePlay class="w-5 h-5" />
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
                        <Settings class="w-5 h-5" />
                    </div>
                </button>
            </div>

            {#if showOptions}
                <div
                    class="p-4 bg-bg-alt dark:bg-dark-bg-alt border border-border-default dark:border-dark-border-default rounded-lg flex space-x-4"
                    transition:slide={{ duration: 300, easing: (t) => 1 - Math.pow(1 - t, 3) }}
                >
                    <div class="w-1/2">
                        <ScriptActions
                            {authenticated}
                            onnew={newScript}
                            onupload={() => fileInput.click()}
                            onsave={saveScript}
                            onexport={exportScript}
                        />
                    </div>
                    <div class="border-l border-border-default dark:border-dark-border-default"></div>
                    <div class="w-1/2">
                        {#if authenticated}
                            <SavedScripts
                                scripts={savedScripts}
                                onload={loadScript}
                                ondelete={deleteScript}
                                onrefresh={refreshScripts}
                            />
                        {:else}
                            <div class="flex flex-col items-center justify-center h-full text-center">
                                <h4
                                    class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider mb-2"
                                >
                                    Saved Scripts
                                </h4>
                                <p class="text-xs text-fg-muted dark:text-dark-fg-muted">
                                    <a href="/login" class="link">Log in</a> to save and manage your scripts.
                                </p>
                            </div>
                        {/if}
                    </div>
                </div>
            {/if}
        </div>
    </div>
</div>
