<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import { fade, slide } from 'svelte/transition';
    import { get, writable } from 'svelte/store';
    import { isAuthenticated, verifyAuth } from '$stores/auth';
    import {
        getK8sResourceLimitsApiV1K8sLimitsGet,
        getExampleScriptsApiV1ExampleScriptsGet,
        listSavedScriptsApiV1ScriptsGet,
        createSavedScriptApiV1ScriptsPost,
        updateSavedScriptApiV1ScriptsScriptIdPut,
        deleteSavedScriptApiV1ScriptsScriptIdDelete,
        type ResourceLimits,
        type LanguageInfo,
    } from '$lib/api';
    import { addToast } from '$stores/toastStore';
    import { unwrap, unwrapOr } from '$lib/api-interceptors';
    import Spinner from '$components/Spinner.svelte';
    import { updateMetaTags, pageMeta } from '$utils/meta';
    import { editorSettings as editorSettingsStore } from '$stores/userSettings';
    import { CirclePlay, Settings, Lightbulb } from '@lucide/svelte';
    import { createExecutionState } from '$lib/editor';
    import {
        CodeMirrorEditor,
        OutputPanel,
        LanguageSelect,
        ResourceLimits as ResourceLimitsPanel,
        EditorToolbar,
        ScriptActions,
        SavedScripts
    } from '$components/editor';

    interface SavedScript {
        id: string;
        name: string;
        script: string;
        lang?: string;
        lang_version?: string;
    }

    function createPersistentStore<T>(key: string, startValue: T) {
        if (typeof localStorage === 'undefined') {
            return writable<T>(startValue);
        }
        const storedValue = localStorage.getItem(key);
        let parsedValue: T = startValue;
        if (storedValue) {
            try {
                parsedValue = JSON.parse(storedValue) as T;
            } catch {
                localStorage.removeItem(key);
            }
        }
        const { subscribe, set, update } = writable<T>(parsedValue);
        return {
            subscribe,
            set(value: T) {
                set(value);
                localStorage.setItem(key, JSON.stringify(value));
            },
            update(fn: (value: T) => T) {
                update(v => {
                    const newValue = fn(v);
                    localStorage.setItem(key, JSON.stringify(newValue));
                    return newValue;
                });
            }
        };
    }

    // Stores
    const script = createPersistentStore('script', "# Welcome to Integr8sCode!\n\nprint('Hello, Kubernetes!')");
    const scriptName = createPersistentStore('scriptName', '');
    const currentScriptId = createPersistentStore<string | null>('currentScriptId', null);
    const selectedLang = writable('python');
    const selectedVersion = writable('3.11');

    // State
    let authenticated = $state(false);
    let k8sLimits = $state<ResourceLimits | null>(null);
    let supportedRuntimes = $state<Record<string, LanguageInfo>>({});
    let exampleScripts: Record<string, string> = {};
    let savedScripts = $state<SavedScript[]>([]);
    let showOptions = $state(false);
    let editorSettings = $state({ theme: 'auto', font_size: 14, tab_size: 4, use_tabs: false, word_wrap: true, show_line_numbers: true });
    let fileInput: HTMLInputElement;
    let editorRef: CodeMirrorEditor;

    const execution = createExecutionState();
    const runtimesAvailable = $derived(Object.keys(supportedRuntimes).length > 0);
    const acceptedFileExts = $derived(Object.values(supportedRuntimes).map(i => `.${i.file_ext}`).join(',') || '.txt');

    // Reactive store values for $effect
    let currentScriptIdValue = $state<string | null>(null);
    let scriptNameValue = $state('');

    let unsubscribeAuth: (() => void) | undefined;
    let unsubscribeSettings: (() => void) | undefined;
    let unsubscribeScriptId: (() => void) | undefined;
    let unsubscribeScriptName: (() => void) | undefined;

    $effect(() => {
        if (typeof window !== 'undefined' && currentScriptIdValue && savedScripts.length > 0) {
            const saved = savedScripts.find(s => s.id === currentScriptIdValue);
            if (saved && saved.name !== scriptNameValue) {
                currentScriptId.set(null);
                addToast('Script name changed. Next save will create a new script.', 'info');
            }
        }
    });

    onMount(async () => {
        updateMetaTags(pageMeta.editor.title, pageMeta.editor.description);

        unsubscribeScriptId = currentScriptId.subscribe(v => currentScriptIdValue = v);
        unsubscribeScriptName = scriptName.subscribe(v => scriptNameValue = v);

        await verifyAuth();

        unsubscribeSettings = editorSettingsStore.subscribe(s => editorSettings = s);
        unsubscribeAuth = isAuthenticated.subscribe(async authStatus => {
            const wasAuthenticated = authenticated;
            authenticated = authStatus;
            if (!wasAuthenticated && authenticated) await loadSavedScripts();
            else if (wasAuthenticated && !authenticated) {
                savedScripts = [];
                currentScriptId.set(null);
                scriptName.set('');
            }
        });

        const { data: limitsData, error: limitsError } = await getK8sResourceLimitsApiV1K8sLimitsGet({});
        if (limitsError) {
            addToast('Failed to load runtime configuration. Execution disabled.', 'error');
        } else {
            k8sLimits = limitsData;
            supportedRuntimes = k8sLimits?.supported_runtimes || {};
            const lang = get(selectedLang);
            const ver = get(selectedVersion);
            const info = supportedRuntimes[lang];
            if (!info || !info.versions.includes(ver)) {
                const first = Object.keys(supportedRuntimes)[0];
                if (first) {
                    selectedLang.set(first);
                    selectedVersion.set(supportedRuntimes[first].versions[0] || '');
                }
            }
        }

        const { data: examplesData } = await getExampleScriptsApiV1ExampleScriptsGet({});
        exampleScripts = examplesData?.scripts || {};

        if (authenticated) await loadSavedScripts();
    });

    onDestroy(() => {
        unsubscribeAuth?.();
        unsubscribeSettings?.();
        unsubscribeScriptId?.();
        unsubscribeScriptName?.();
    });

    async function loadSavedScripts() {
        if (!authenticated) return;
        const data = unwrapOr(await listSavedScriptsApiV1ScriptsGet({}), null);
        savedScripts = (data || []).map((s, i) => ({ ...s, id: s.id || s._id || `temp_${i}_${Date.now()}` }));
    }

    function loadScript(s: SavedScript) {
        script.set(s.script);
        scriptName.set(s.name);
        currentScriptId.set(s.id);
        if (s.lang) selectedLang.set(s.lang);
        if (s.lang_version) selectedVersion.set(s.lang_version);
        editorRef?.setContent(s.script);
        execution.reset();
        addToast(`Loaded script: ${s.name}`, 'info');
        showOptions = false;
    }

    async function saveScript() {
        if (!authenticated) { addToast('Please log in to save scripts.', 'warning'); return; }
        const name = get(scriptName);
        if (!name.trim()) { addToast('Please provide a name for your script.', 'warning'); return; }

        const body = { name, script: get(script), lang: get(selectedLang), lang_version: get(selectedVersion) };
        const id = get(currentScriptId);

        if (id) {
            const { error, response } = await updateSavedScriptApiV1ScriptsScriptIdPut({ path: { script_id: id }, body });
            if (error) {
                if (response?.status === 404) {
                    currentScriptId.set(null);
                    const data = unwrap(await createSavedScriptApiV1ScriptsPost({ body }));
                    currentScriptId.set(data.id);
                    addToast('Script saved successfully.', 'success');
                }
                return;
            }
            addToast('Script updated successfully.', 'success');
        } else {
            const data = unwrap(await createSavedScriptApiV1ScriptsPost({ body }));
            currentScriptId.set(data.id);
            addToast('Script saved successfully.', 'success');
        }
        await loadSavedScripts();
    }

    async function deleteScript(id: string) {
        const s = savedScripts.find(x => x.id === id);
        if (!confirm(s ? `Are you sure you want to delete "${s.name}"?` : 'Are you sure you want to delete this script?')) return;
        unwrap(await deleteSavedScriptApiV1ScriptsScriptIdDelete({ path: { script_id: id } }));
        addToast('Script deleted successfully.', 'success');
        if (get(currentScriptId) === id) newScript();
        await loadSavedScripts();
    }

    function newScript() {
        script.set('');
        scriptName.set('');
        currentScriptId.set(null);
        editorRef?.setContent('');
        execution.reset();
        addToast('New script started.', 'info');
    }

    function exportScript() {
        const content = get(script);
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const lang = get(selectedLang);
        const ext = supportedRuntimes[lang]?.file_ext || 'txt';
        let filename = get(scriptName).trim() || `script.${ext}`;
        if (!filename.toLowerCase().endsWith(`.${ext}`)) filename = filename.replace(/\.[^.]+$/, '') + `.${ext}`;
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function handleFileUpload(event: Event) {
        const file = (event.target as HTMLInputElement).files?.[0];
        if (!file) return;

        const extToLang: Record<string, string> = {};
        for (const [lang, info] of Object.entries(supportedRuntimes)) extToLang[info.file_ext] = lang;

        const fileExt = file.name.split('.').pop()?.toLowerCase() || '';
        const detectedLang = extToLang[fileExt];

        if (!detectedLang) {
            addToast(`Unsupported file type. Allowed: ${Object.values(supportedRuntimes).map(i => `.${i.file_ext}`).join(', ')}`, 'error');
            return;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            const text = e.target?.result as string;
            newScript();
            script.set(text);
            scriptName.set(file.name);
            selectedLang.set(detectedLang);
            const info = supportedRuntimes[detectedLang];
            if (info?.versions.length) selectedVersion.set(info.versions[0]);
            editorRef?.setContent(text);
            addToast(`Loaded ${detectedLang} script from ${file.name}`, 'info');
        };
        reader.onerror = () => addToast('Failed to read the selected file.', 'error');
        reader.readAsText(file);
        (event.target as HTMLInputElement).value = '';
    }

    function loadExampleScript() {
        const lang = get(selectedLang);
        const example = exampleScripts[lang];
        if (!example) { addToast(`No example script available for ${lang}.`, 'warning'); return; }

        const lines = example.split('\n');
        const firstLine = lines.find((l: string) => l.trim().length > 0);
        const indent = firstLine ? (firstLine.match(/^\s*/) ?? [''])[0] : '';
        const cleaned = lines.map((l: string) => l.startsWith(indent) ? l.substring(indent.length) : l).join('\n').trim();

        script.set(cleaned);
        editorRef?.setContent(cleaned);
        execution.reset();
        addToast(`Loaded example script for ${lang}.`, 'info');
    }

    function handleExecute() {
        execution.execute(get(script), get(selectedLang), get(selectedVersion));
    }
</script>

<input type="file" accept={acceptedFileExts} bind:this={fileInput} class="hidden" onchange={handleFileUpload} />

<div class="editor-grid-container space-y-4 md:space-y-0 md:gap-6" in:fade={{ duration: 300 }}>
    <div class="editor-header flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h2 class="text-xl sm:text-2xl font-semibold text-fg-default dark:text-dark-fg-default whitespace-nowrap">Code Editor</h2>
        <ResourceLimitsPanel limits={k8sLimits} />
    </div>

    <div class="editor-main-code flex flex-col rounded-lg overflow-hidden shadow-md border border-border-default dark:border-dark-border-default">
        <EditorToolbar name={$scriptName} onchange={(n) => scriptName.set(n)} onexample={loadExampleScript} />
        <div class="editor-wrapper h-full w-full relative">
            <CodeMirrorEditor
                bind:this={editorRef}
                bind:content={$script}
                lang={$selectedLang}
                settings={editorSettings}
            />
            {#if $script.trim() === ''}
                <div class="absolute inset-0 flex flex-col items-center justify-center p-4 text-center pointer-events-none">
                    <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default">Editor is Empty</h3>
                    <p class="text-sm text-fg-muted dark:text-dark-fg-muted mt-1 mb-4">Start typing, upload a file, or use an example to begin.</p>
                    <button class="btn btn-primary inline-flex items-center space-x-2 pointer-events-auto" onclick={loadExampleScript}>
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
                    lang={$selectedLang}
                    version={$selectedVersion}
                    onselect={(l, v) => { selectedLang.set(l); selectedVersion.set(v); }}
                />
                <button class="btn btn-primary btn-sm flex-grow sm:flex-grow-0 min-w-[130px]" onclick={handleExecute}
                        disabled={execution.isExecuting || !runtimesAvailable}>
                    <CirclePlay class="w-5 h-5" />
                    <span class="ml-1.5">{execution.isExecuting ? 'Executing...' : 'Run Script'}</span>
                </button>
                <button class="btn btn-secondary-outline btn-sm btn-icon ml-auto sm:ml-2"
                        onclick={() => showOptions = !showOptions}
                        aria-expanded={showOptions}
                        title={showOptions ? 'Hide Options' : 'Show Options'}>
                    <span class="sr-only">Toggle Script Options</span>
                    <div class="transition-transform duration-300 ease-out-expo" class:rotate-90={showOptions}>
                        <Settings class="w-5 h-5" />
                    </div>
                </button>
            </div>

            {#if showOptions}
                <div class="p-4 bg-bg-alt dark:bg-dark-bg-alt border border-border-default dark:border-dark-border-default rounded-lg flex space-x-4"
                     transition:slide={{ duration: 300, easing: (t) => 1 - Math.pow(1 - t, 3) }}>
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
                                onrefresh={loadSavedScripts}
                            />
                        {:else}
                            <div class="flex flex-col items-center justify-center h-full text-center">
                                <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider mb-2">Saved Scripts</h4>
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
