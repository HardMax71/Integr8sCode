<script lang="ts">
    import {onDestroy, onMount} from "svelte";
    import {fade, fly, slide} from "svelte/transition";
    import {get, writable} from "svelte/store";
    import {isAuthenticated, logout as authLogout, verifyAuth, csrfToken} from "../stores/auth";
    import {
        getK8sResourceLimitsApiV1K8sLimitsGet,
        getExampleScriptsApiV1ExampleScriptsGet,
        createExecutionApiV1ExecutePost,
        getResultApiV1ResultExecutionIdGet,
        listSavedScriptsApiV1ScriptsGet,
        createSavedScriptApiV1ScriptsPost,
        updateSavedScriptApiV1ScriptsScriptIdPut,
        deleteSavedScriptApiV1ScriptsScriptIdDelete,
        type K8sResourceLimits,
        type ExecutionResult,
        type LanguageInfo,
    } from "../lib/api";

    // Local interface for saved script data used in the editor
    interface EditorScriptData {
        id: string;
        name: string;
        script: string;
        lang?: string;
        lang_version?: string;
    }

    import {addToast} from "../stores/toastStore";
    import {getErrorMessage, unwrap, unwrapOr} from "../lib/api-interceptors";
    import Spinner from "../components/Spinner.svelte";
    import {goto} from "@mateothegreat/svelte5-router";
    import {Compartment, EditorState, StateEffect} from "@codemirror/state";
    import {EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers} from "@codemirror/view";
    import {defaultKeymap, history, historyKeymap, indentWithTab} from "@codemirror/commands";
    import {python} from "@codemirror/lang-python";
    import {javascript} from "@codemirror/lang-javascript";
    import {go} from "@codemirror/lang-go";
    import {StreamLanguage} from "@codemirror/language";
    import {ruby} from "@codemirror/legacy-modes/mode/ruby";
    import {shell} from "@codemirror/legacy-modes/mode/shell";
    import {oneDark} from "@codemirror/theme-one-dark";
    import {githubLight} from "@uiw/codemirror-theme-github";
    import {bracketMatching} from "@codemirror/language";
    import {autocompletion, completionKeymap} from "@codemirror/autocomplete";
    import {theme as appTheme} from "../stores/theme";
    import AnsiToHtml from 'ansi-to-html';
    import DOMPurify from 'dompurify';
    import { updateMetaTags, pageMeta } from '../utils/meta';
    import { editorSettings as editorSettingsStore } from '../stores/userSettings';
    import { saveUserSettings } from '../lib/user-settings';
    import { MessageSquare, ChevronDown, ChevronUp, ChevronRight, Cpu, MemoryStick, Clock, CirclePlay, Settings, FilePlus, Upload, Download, Save, List, Trash2, FileText, Copy, Lightbulb, AlertTriangle } from '@lucide/svelte';

    let themeCompartment = new Compartment();
    let fontSizeCompartment = new Compartment();
    let tabSizeCompartment = new Compartment();
    let lineNumbersCompartment = new Compartment();
    let lineWrappingCompartment = new Compartment();
    let languageCompartment = new Compartment();

    // Language extension mapping
    function getLanguageExtension(lang: string) {
        switch (lang) {
            case 'python': return python();
            case 'node': return javascript();
            case 'go': return go();
            case 'ruby': return StreamLanguage.define(ruby);
            case 'bash': return StreamLanguage.define(shell);
            default: return python();
        }
    }

    // Default editor settings
    let editorSettings = {
        theme: 'auto',  // Default to following app theme
        font_size: 14,
        tab_size: 4,
        use_tabs: false,
        word_wrap: true,
        show_line_numbers: true,
    };
    
    // Editor theme mapping
    const editorThemes = {
        'one-dark': oneDark,
        'github': githubLight,
        'auto': null  // Will be determined by app theme
    };

    const ansiConverter = new AnsiToHtml({
        fg: '#000',
        bg: '#FFF',
        newline: true,
        escapeXML: true,
        stream: false,
        colors: {
            0: '#000',
            1: '#C00',
            2: '#0C0',
            3: '#C50',
            4: '#00C',
            5: '#C0C',
            6: '#0CC',
            7: '#CCC',
            8: '#555',
            9: '#F55',
            10: '#5F5',
            11: '#FF5',
            12: '#55F',
            13: '#F5F',
            14: '#5FF',
            15: '#FFF'
        }
    });

    function sanitizeOutput(html: string): string {
        return DOMPurify.sanitize(html, {
            ALLOWED_TAGS: ['span', 'br', 'div'],
            ALLOWED_ATTR: ['class', 'style']
        });
    }

    function createPersistentStore<T>(key: string, startValue: T): { subscribe: typeof store.subscribe; set: typeof store.set } {
        if (typeof localStorage === 'undefined') {
            const store = writable<T>(startValue);
            return {subscribe: store.subscribe, set: store.set};
        }
        const storedValue = localStorage.getItem(key);
        let parsedValue: T = startValue;

        if (storedValue) {
            try {
                parsedValue = JSON.parse(storedValue) as T;
            } catch (e) {
                console.warn(`Failed to parse localStorage value for ${key}, using default:`, e);
                localStorage.removeItem(key); // Clear corrupted value
            }
        }

        const store = writable<T>(parsedValue);
        store.subscribe(value => {
            localStorage.setItem(key, JSON.stringify(value));
        });
        return store;
    }

    let script = createPersistentStore("script", "# Welcome to Integr8sCode!\n\nprint('Hello, Kubernetes!')");
    let executing = $state(false);
    let executionStatus = $state<string | null>(null); // Progress status during execution (queued, running, etc.)
    let result = $state<ExecutionResult | null>(null);
    let editorView = $state<EditorView | null>(null);
    let editorContainer: HTMLElement;
    let k8sLimits = $state<K8sResourceLimits | null>(null);
    let exampleScripts: Record<string, any> = {};

    // Updated state for language and version selection
    let selectedLang = writable("python");
    let selectedVersion = writable("3.11");
    let supportedRuntimes = $state<Record<string, LanguageInfo>>({});
    let acceptedFileExts = $derived(
        Object.values(supportedRuntimes).map(i => `.${i.file_ext}`).join(',') || '.txt'
    );
    let runtimesAvailable = $derived(Object.keys(supportedRuntimes).length > 0);
    let showLangOptions = $state(false);
    let hoveredLang = $state<string | null>(null);

    let showLimits = $state(false);
    let showOptions = $state(false);
    let showSavedScripts = $state(false);

    let authenticated = $state(false);
    let savedScripts = $state<any[]>([]);
    let scriptName = createPersistentStore("scriptName", "");
    let currentScriptId = createPersistentStore("currentScriptId", null);

    // Reactive state for tracking store values in $effect
    let currentScriptIdValue = $state<string | null>(null);
    let scriptNameValue = $state("");

    let fileInput: HTMLInputElement;
    let apiError = $state<string | null>(null);
    let unsubscribeAuth;
    let unsubscribeTheme;
    let unsubscribeSettings;
    let unsubscribeScriptId;
    let unsubscribeScriptName;
    let unsubscribeLang;


    // Watch for script name changes and clear ID if name changed
    // Uses reactive state variables that are kept in sync with stores via subscriptions
    $effect(() => {
        if (typeof window !== 'undefined') {
            // Access reactive state variables - this creates proper dependencies
            const currentId = currentScriptIdValue;
            const currentName = scriptNameValue;

            if (currentId && savedScripts && savedScripts.length > 0) {
                const associatedSavedScript = savedScripts.find(s => s.id === currentId);

                // If the name in the input box has been changed and no longer matches
                // the name of the script we have loaded, clear the ID.
                if (associatedSavedScript && associatedSavedScript.name !== currentName) {
                    currentScriptId.set(null);
                    addToast('Script name changed. Next save will create a new script.', 'info');
                }
            }
        }
    });

    onMount(async () => {
        // Set meta tags
        updateMetaTags(pageMeta.editor.title, pageMeta.editor.description);

        // Subscribe to script stores for reactive $effect tracking
        unsubscribeScriptId = currentScriptId.subscribe(value => {
            currentScriptIdValue = value;
        });
        unsubscribeScriptName = scriptName.subscribe(value => {
            scriptNameValue = value;
        });

        // Verify authentication status on startup
        await verifyAuth();

        // Subscribe to editor settings store (populated by AuthInitializer)
        unsubscribeSettings = editorSettingsStore.subscribe(storeSettings => {
            editorSettings = storeSettings;
            if (editorView) {
                applyEditorSettings();
            }
        });

        unsubscribeAuth = isAuthenticated.subscribe(authStatus => {
            const wasAuthenticated = authenticated;
            authenticated = authStatus;
            if (!wasAuthenticated && authenticated && editorView) {
                loadSavedScripts();
            } else if (wasAuthenticated && !authenticated) {
                savedScripts = [];
                showSavedScripts = false;
                currentScriptId.set(null);
                scriptName.set("");
            }
        });

        const { data: limitsData, error: limitsError } = await getK8sResourceLimitsApiV1K8sLimitsGet({});
        if (limitsError) {
            addToast("Failed to load runtime configuration. Execution disabled.", "error");
            supportedRuntimes = {};
        } else {
            k8sLimits = limitsData;
            supportedRuntimes = k8sLimits?.supported_runtimes || {};
            const currentLang = get(selectedLang);
            const currentVersion = get(selectedVersion);
            const langInfo = supportedRuntimes[currentLang];
            if (!langInfo || !langInfo.versions.includes(currentVersion)) {
                const firstLang = Object.keys(supportedRuntimes)[0];
                if (firstLang) {
                    const firstVersion = supportedRuntimes[firstLang].versions[0];
                    selectedLang.set(firstLang);
                    if (firstVersion) selectedVersion.set(firstVersion);
                }
            }
        }

        const { data: examplesData, error: examplesError } = await getExampleScriptsApiV1ExampleScriptsGet({});
        if (!examplesError) exampleScripts = examplesData?.scripts || {};

        // Delay initialization to ensure DOM is ready
        setTimeout(() => {
            initializeEditor(get(appTheme));
        }, 100);

        unsubscribeTheme = appTheme.subscribe(currentTheme => {
            // Update editor theme when app theme changes
            if (editorView) {
                // Just apply settings - the logic is already in applyEditorSettings
                applyEditorSettings();
            }
        });

        unsubscribeLang = selectedLang.subscribe(lang => {
            // Update syntax highlighting when language changes
            if (editorView) {
                editorView.dispatch({
                    effects: languageCompartment.reconfigure(getLanguageExtension(lang))
                });
            }
        });

        if (authenticated) {
            await loadSavedScripts();
        }
    });

    onDestroy(() => {
        if (editorView) {
            editorView.destroy();
            editorView = null;
        }
        if (unsubscribeAuth) unsubscribeAuth();
        if (unsubscribeTheme) unsubscribeTheme();
        if (unsubscribeSettings) unsubscribeSettings();
        if (unsubscribeScriptId) unsubscribeScriptId();
        if (unsubscribeScriptName) unsubscribeScriptName();
        if (unsubscribeLang) unsubscribeLang();
    });

    function getStaticExtensions() {
        return [
            lineNumbersCompartment.of(editorSettings.show_line_numbers ? lineNumbers() : []),
            highlightActiveLineGutter(),
            highlightActiveLine(),
            history(),
            bracketMatching(),
            autocompletion(),
            EditorState.allowMultipleSelections.of(true),
            tabSizeCompartment.of(EditorState.tabSize.of(editorSettings.tab_size)),
            keymap.of([
                ...defaultKeymap,
                ...historyKeymap,
                ...completionKeymap,
                indentWithTab
            ]),
            languageCompartment.of(getLanguageExtension(get(selectedLang))),
            lineWrappingCompartment.of(editorSettings.word_wrap ? EditorView.lineWrapping : []),
            fontSizeCompartment.of(EditorView.theme({
                ".cm-content": {
                    fontSize: `${editorSettings.font_size}px`
                }
            })),
            EditorView.theme({
                "&": {
                    height: "100%",
                    maxHeight: "100%"
                },
                ".cm-content": {
                    minHeight: "100%"
                },
                ".cm-scroller": {
                    overflow: "auto",
                    maxHeight: "100%"
                }
            }),
            EditorView.updateListener.of(update => {
                if (update.docChanged) {
                    script.set(update.state.doc.toString());
                }
            }),
        ];
    }

    function applyEditorSettings() {
        if (!editorView) return;
        
        // Apply theme
        let newTheme;
        if (editorSettings.theme === 'auto' || !editorThemes[editorSettings.theme]) {
            // Use app theme
            const currentAppTheme = get(appTheme);
            newTheme = currentAppTheme === 'dark' ? oneDark : githubLight;
            console.log('Applying auto theme:', currentAppTheme, '-> editor theme:', newTheme === oneDark ? 'one-dark' : 'github');
        } else {
            newTheme = editorThemes[editorSettings.theme];
            console.log('Applying fixed theme:', editorSettings.theme);
        }
        
        editorView.dispatch({
            effects: themeCompartment.reconfigure(newTheme)
        });
        
        // Apply font size
        editorView.dispatch({
            effects: fontSizeCompartment.reconfigure(EditorView.theme({
                ".cm-content": {
                    fontSize: `${editorSettings.font_size}px`
                }
            }))
        });
        
        // Apply tab size
        editorView.dispatch({
            effects: tabSizeCompartment.reconfigure(EditorState.tabSize.of(editorSettings.tab_size))
        });
        
        // Apply line numbers
        editorView.dispatch({
            effects: lineNumbersCompartment.reconfigure(editorSettings.show_line_numbers ? lineNumbers() : [])
        });
        
        // Apply line wrapping
        editorView.dispatch({
            effects: lineWrappingCompartment.reconfigure(editorSettings.word_wrap ? EditorView.lineWrapping : [])
        });
    }
    
    function initializeEditor(currentTheme: string): void {
        if (!editorContainer || editorView) return;

        let initialThemeExtension;
        if (editorSettings.theme === 'auto' || !editorThemes[editorSettings.theme]) {
            initialThemeExtension = currentTheme === 'dark' ? oneDark : githubLight;
            console.log('Initializing editor with auto theme:', currentTheme, '-> editor theme:', initialThemeExtension === oneDark ? 'one-dark' : 'github');
        } else {
            initialThemeExtension = editorThemes[editorSettings.theme];
            console.log('Initializing editor with fixed theme:', editorSettings.theme);
        }

        try {
            const startState = EditorState.create({
                doc: get(script),
                extensions: [
                    ...getStaticExtensions(),
                    themeCompartment.of(initialThemeExtension)
                ],
            });

            editorView = new EditorView({
                state: startState,
                parent: editorContainer,
            });
        } catch (e) {
            console.error("Failed to initialize CodeMirror:", e);
            addToast("Failed to load code editor.", "error");
        }
    }

    async function executeScript() {
        executing = true;
        executionStatus = 'starting';
        apiError = null;
        result = null;

        const scriptValue = get(script);
        const langValue = get(selectedLang);
        const versionValue = get(selectedVersion);
        let executionId: string | null = null;

        try {
            // 1. Start execution
            const { data: executeData, error: execError } = await createExecutionApiV1ExecutePost({
                body: {
                    script: scriptValue,
                    lang: langValue,
                    lang_version: versionValue
                }
            });
            if (execError) throw execError;

            executionId = executeData.execution_id;
            executionStatus = executeData.status || 'queued';

            // 2. Connect to SSE for real-time updates
            const finalResult = await new Promise<ExecutionResult>((resolve, reject) => {
                const eventSource = new EventSource(`/api/v1/events/executions/${executionId}`, {
                    withCredentials: true
                });

                const fetchResultFallback = async () => {
                    try {
                        const { data, error } = await getResultApiV1ResultExecutionIdGet({
                            path: { execution_id: executionId! }
                        });
                        if (error) throw error;
                        resolve(data!);
                    } catch (e) {
                        reject(e);
                    }
                };

                eventSource.onmessage = async (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        const eventType = data?.event_type || data?.type;

                        // Ignore heartbeat/connected events
                        if (eventType === 'heartbeat' || eventType === 'connected') {
                            return;
                        }

                        // Update status for progress display
                        if (data.status) {
                            executionStatus = data.status;
                        }

                        // Terminal event: result_stored contains the full result
                        if (eventType === 'result_stored' && data.result) {
                            eventSource.close();
                            resolve(data.result);
                            return;
                        }

                        // Other terminal events: fetch result from API
                        if (eventType === 'execution_failed' ||
                            eventType === 'execution_timeout' ||
                            eventType === 'result_failed') {
                            eventSource.close();
                            await fetchResultFallback();
                        }
                    } catch (err) {
                        console.error('Error processing SSE event:', err);
                    }
                };

                eventSource.onerror = () => {
                    console.error('SSE connection error, fetching result via API');
                    eventSource.close();
                    fetchResultFallback();
                };
            });

            result = finalResult;

        } catch (err) {
            apiError = getErrorMessage(err, "Error executing script.");
            // If we have an execution_id, try to fetch the result anyway
            if (executionId) {
                try {
                    const { data } = await getResultApiV1ResultExecutionIdGet({
                        path: { execution_id: executionId }
                    });
                    if (data) {
                        result = data;
                        apiError = null; // Clear error since we got a result
                    }
                } catch {
                    // Keep the apiError
                }
            }
        } finally {
            executing = false;
            executionStatus = null;
        }
    }

    async function loadSavedScripts() {
        if (!authenticated) return;
        const data = unwrapOr(await listSavedScriptsApiV1ScriptsGet({}), null);
        savedScripts = (data || []).map((script, index) => ({
            ...script,
            id: script.id || script._id || `temp_${index}_${Date.now()}`
        }));
    }

    function loadScript(scriptData: EditorScriptData): void {
        if (!editorView) return;
        script.set(scriptData.script);
        scriptName.set(scriptData.name);
        currentScriptId.set(scriptData.id);

        // Set language and version if available in the saved script
        if (scriptData.lang) {
            selectedLang.set(scriptData.lang);
        }
        if (scriptData.lang_version) {
            selectedVersion.set(scriptData.lang_version);
        }

        editorView.dispatch({
            changes: {
                from: 0,
                to: editorView.state.doc.length,
                insert: scriptData.script,
            },
            selection: {anchor: 0}
        });
        addToast(`Loaded script: ${scriptData.name}`, "info");
        showSavedScripts = false;
        showOptions = false;
        result = null;
        apiError = null;
        executionStatus = null;
    }

    async function saveScript() {
        if (!authenticated) {
            addToast("Please log in to save scripts.", "warning");
            return;
        }
        const nameValue = get(scriptName);
        if (!nameValue.trim()) {
            addToast("Please provide a name for your script.", "warning");
            return;
        }
        const scriptData = {
            name: nameValue,
            script: get(script),
            lang: get(selectedLang),
            lang_version: get(selectedVersion)
        };
        const currentIdValue = get(currentScriptId);

        if (currentIdValue) {
            const { error: updateErr, response: updateResp } = await updateSavedScriptApiV1ScriptsScriptIdPut({
                path: { script_id: currentIdValue },
                body: scriptData
            });
            if (updateErr) {
                if (updateResp?.status === 404) {
                    currentScriptId.set(null);
                    const data = unwrap(await createSavedScriptApiV1ScriptsPost({ body: scriptData }));
                    currentScriptId.set(data.id);
                    addToast("Script saved successfully.", "success");
                }
                return;
            }
            addToast("Script updated successfully.", "success");
        } else {
            const data = unwrap(await createSavedScriptApiV1ScriptsPost({ body: scriptData }));
            currentScriptId.set(data.id);
            addToast("Script saved successfully.", "success");
        }
        await loadSavedScripts();
    }

    async function deleteScript(scriptIdToDelete: string): Promise<void> {
        if (!authenticated) return;
        const scriptToDelete = savedScripts.find(s => s.id === scriptIdToDelete);
        const confirmMessage = scriptToDelete
            ? `Are you sure you want to delete "${scriptToDelete.name}"?`
            : "Are you sure you want to delete this script?";
        if (!confirm(confirmMessage)) return;

        unwrap(await deleteSavedScriptApiV1ScriptsScriptIdDelete({
            path: { script_id: scriptIdToDelete }
        }));
        addToast("Script deleted successfully.", "success");
        if (get(currentScriptId) === scriptIdToDelete) newScript();
        await loadSavedScripts();
    }

    function newScript() {
        if (!editorView) return;
        script.set("");
        scriptName.set("");
        currentScriptId.set(null);
        editorView.dispatch({
            changes: {from: 0, to: editorView.state.doc.length, insert: ""},
            selection: {anchor: 0}
        });
        result = null;
        apiError = null;
        executionStatus = null;
        addToast("New script started.", "info");
    }

    function exportScript() {
        const scriptValue = get(script);
        const blob = new Blob([scriptValue], {type: "text/plain;charset=utf-8"});
        const url = URL.createObjectURL(blob);
        const lang = get(selectedLang);
        const langInfo = supportedRuntimes[lang];
        const ext = langInfo?.file_ext || "txt";
        let filename = get(scriptName).trim() || `script.${ext}`;
        if (!filename.toLowerCase().endsWith(`.${ext}`)) {
            filename = filename.replace(/\.[^.]+$/, "") + `.${ext}`;
        }
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function handleFileUpload(event: Event): void {
        const target = event.target as HTMLInputElement;
        const file = target.files?.[0];
        if (!file) return;

        // Build extension to language map from supportedRuntimes
        const extToLang: Record<string, string> = {};
        for (const [lang, info] of Object.entries(supportedRuntimes)) {
            extToLang[info.file_ext] = lang;
        }

        // Get file extension
        const fileExt = file.name.split('.').pop()?.toLowerCase() || "";
        const detectedLang = extToLang[fileExt];

        if (!detectedLang) {
            const supportedExts = Object.values(supportedRuntimes).map(i => `.${i.file_ext}`).join(", ");
            addToast(`Unsupported file type. Allowed: ${supportedExts}`, "error");
            return;
        }

        const reader = new FileReader();
        reader.onload = (e: ProgressEvent<FileReader>) => {
            const text = e.target?.result as string;
            if (editorView) {
                newScript();
                script.set(text);
                scriptName.set(file.name);

                // Auto-select detected language and first available version
                selectedLang.set(detectedLang);
                const langInfo = supportedRuntimes[detectedLang];
                if (langInfo?.versions.length > 0) {
                    selectedVersion.set(langInfo.versions[0]);
                }

                editorView.dispatch({
                    changes: {from: 0, to: editorView.state.doc.length, insert: text},
                    selection: {anchor: 0}
                });
                addToast(`Loaded ${detectedLang} script from ${file.name}`, "info");
            }
        };
        reader.onerror = () => {
            addToast("Failed to read the selected file.", "error");
        };
        reader.readAsText(file);
        target.value = '';
    }

    function handleLogout(): void {
        authLogout();
        goto("/login");
        addToast("You have been logged out.", "info");
    }

    function toggleLimits(): void {
        showLimits = !showLimits;
    }

    function toggleOptions(): void {
        showOptions = !showOptions;
        if (!showOptions) showSavedScripts = false;
    }

    function toggleSavedScripts(): void {
        showSavedScripts = !showSavedScripts;
        if (showSavedScripts && authenticated) {
            loadSavedScripts();
        }
    }

    function loadExampleScript(): void {
        if (!editorView) return;
        const lang = get(selectedLang);
        const example = exampleScripts[lang];

        if (example) {
            const lines = example.split('\n');
            const firstLine = lines.find((line: string) => line.trim().length > 0);
            const indentation = firstLine ? (firstLine.match(/^\s*/) ?? [''])[0] : '';
            const cleanedScript = lines.map((line: string) => line.startsWith(indentation) ? line.substring(indentation.length) : line).join('\n').trim();

            script.set(cleanedScript);
            editorView.dispatch({
                changes: {
                    from: 0,
                    to: editorView.state.doc.length,
                    insert: cleanedScript,
                },
                selection: {anchor: 0}
            });
            addToast(`Loaded example script for ${lang}.`, "info");
            result = null;
            apiError = null;
            executionStatus = null;
        } else {
            addToast(`No example script available for ${lang}.`, "warning");
        }
    }

    async function copyExecutionId(executionId: string): Promise<void> {
        try {
            await navigator.clipboard.writeText(executionId);
            addToast("Execution ID copied to clipboard", "success");
        } catch (err) {
            console.error("Failed to copy execution ID:", err);
            addToast("Failed to copy execution ID", "error");
        }
    }

    async function copyOutput(output: string): Promise<void> {
        try {
            await navigator.clipboard.writeText(output);
            addToast("Output copied to clipboard", "success");
        } catch (err) {
            console.error("Failed to copy output:", err);
            addToast("Failed to copy output", "error");
        }
    }

    async function copyErrors(errors: string): Promise<void> {
        try {
            await navigator.clipboard.writeText(errors);
            addToast("Error text copied to clipboard", "success");
        } catch (err) {
            console.error("Failed to copy errors:", err);
            addToast("Failed to copy errors", "error");
        }
    }
</script>

<input type="file" accept={acceptedFileExts} bind:this={fileInput} class="hidden" onchange={handleFileUpload}/>

<div class="editor-grid-container space-y-4 md:space-y-0 md:gap-6" in:fade={{ duration: 300 }}>
    <div class="editor-header flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h2 class="text-xl sm:text-2xl font-semibold text-fg-default dark:text-dark-fg-default whitespace-nowrap">
            Code Editor
        </h2>
        {#if k8sLimits}
            <div class="relative shrink-0">
                <button class="btn btn-secondary-outline btn-sm inline-flex items-center space-x-1.5 w-full sm:w-auto justify-center"
                        onclick={toggleLimits} aria-expanded={showLimits}>
                    <MessageSquare class="w-4 h-4" />
                    <span>Resource Limits</span>
                    {#if showLimits} <ChevronUp class="w-4 h-4" /> {:else} <ChevronDown class="w-4 h-4" /> {/if}
                </button>
                {#if showLimits}
                    <div class="absolute right-0 top-full mt-2 w-64 sm:w-72 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-xl ring-1 ring-black/5 dark:ring-white/10 p-5 z-30 border border-border-default dark:border-dark-border-default"
                         transition:fly={{ y: 10, duration: 200 }}>
                        <div class="space-y-4">
                            <div class="flex items-center justify-between text-sm">
                                <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center"><span
                                        class="mr-2"><Cpu class="w-4 h-4" /></span>CPU Limit</span>
                                <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums">{k8sLimits.cpu_limit}</span>
                            </div>
                            <div class="flex items-center justify-between text-sm">
                                <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center"><span
                                        class="mr-2"><MemoryStick class="w-4 h-4" /></span>Memory Limit</span>
                                <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums">{k8sLimits.memory_limit}</span>
                            </div>
                            <div class="flex items-center justify-between text-sm">
                                <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center"><span
                                        class="mr-2"><Clock class="w-4 h-4" /></span>Timeout</span>
                                <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums">{k8sLimits.execution_timeout}
                                    s</span>
                            </div>
                        </div>
                    </div>
                {/if}
            </div>
        {:else if apiError && !k8sLimits}
            <p class="text-xs text-red-600 dark:text-red-400">{apiError}</p>
        {/if}
    </div>

    <div class="editor-main-code flex flex-col rounded-lg overflow-hidden shadow-md border border-border-default dark:border-dark-border-default">
        <div class="editor-toolbar flex items-center justify-between px-3 py-1 bg-bg-default dark:bg-dark-bg-default border-b border-border-default dark:border-dark-border-default shrink-0">
            <div>
                <label for="scriptNameInput" class="sr-only">Script Name</label>
                <input id="scriptNameInput" type="text" class="form-input-bare"
                       placeholder="Unnamed Script" bind:value={$scriptName}/>
            </div>
            <div class="flex items-center space-x-2">
                 <button class="btn btn-secondary-outline btn-sm inline-flex items-center space-x-1.5"
                        onclick={loadExampleScript} title="Load an example script for the selected language">
                    <Lightbulb class="w-4 h-4" />
                    <span class="hidden sm:inline">Example</span>
                </button>
            </div>
        </div>
        <div bind:this={editorContainer} class="editor-wrapper h-full w-full relative">
            {#if !editorView}
                <div class="flex items-center justify-center h-full p-4 text-center text-fg-muted dark:text-dark-fg-muted">
                    <Spinner/>
                    <span class="ml-2">Loading Editor...</span>
                </div>
            {:else if get(script).trim() === ''}
                <div class="absolute inset-0 flex flex-col items-center justify-center p-4 text-center">
                    <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default">Editor is Empty</h3>
                    <p class="text-sm text-fg-muted dark:text-dark-fg-muted mt-1 mb-4">
                        Start typing, upload a file, or use an example to begin.
                    </p>
                    <button class="btn btn-primary inline-flex items-center space-x-2" onclick={loadExampleScript}>
                        <Lightbulb class="w-4 h-4" />
                        <span>Start with an Example</span>
                    </button>
                </div>
            {/if}
        </div>
    </div>

    <div class="editor-main-output">
        <div class="output-container flex flex-col h-full">
            <h3 class="text-base font-medium text-fg-default dark:text-dark-fg-default mb-3 border-b border-border-default dark:border-dark-border-default pb-3 shrink-0">
                Execution Output
            </h3>
            <div class="output-content flex-grow overflow-auto pr-2 text-sm custom-scrollbar">
                {#if executing}
                    <div class="flex flex-col items-center justify-center h-full text-center p-4 animate-fadeIn">
                        <Spinner/>
                        <p class="mt-3 text-sm font-medium text-primary-dark dark:text-primary-light">
                            {#if executionStatus}
                                {executionStatus === 'queued' ? 'Queued...' :
                                 executionStatus === 'running' ? 'Running...' :
                                 executionStatus === 'scheduled' ? 'Scheduled...' :
                                 'Executing...'}
                            {:else}
                                Executing...
                            {/if}
                        </p>
                    </div>
                {:else if apiError && !result}
                    <div class="flex flex-col items-center justify-center h-full text-center p-4 animate-fadeIn">
                        <div class="w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mb-3">
                            <AlertTriangle class="w-6 h-6 text-red-600 dark:text-red-400" />
                        </div>
                        <p class="text-sm font-medium text-red-700 dark:text-red-300">Execution Failed</p>
                        <p class="mt-1 text-xs text-fg-muted dark:text-dark-fg-muted max-w-xs">{apiError}</p>
                    </div>
                {:else if result}
                    <div class="space-y-5 animate-flyIn">
                        <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs">
                            <span class="inline-flex items-center rounded-lg px-2 py-1 font-medium ring-1 ring-inset whitespace-nowrap"
                                  class:bg-green-50={result.status === 'completed'}
                                  class:text-green-700={result.status === 'completed'}
                                  class:ring-green-600={result.status === 'completed'}
                                  class:dark:bg-green-950={result.status === 'completed'}
                                  class:dark:text-green-300={result.status === 'completed'}
                                  class:dark:ring-green-500={result.status === 'completed'}

                                  class:bg-red-50={result.status === 'error' || result.status === 'failed'}
                                  class:text-red-700={result.status === 'error' || result.status === 'failed'}
                                  class:ring-red-600={result.status === 'error' || result.status === 'failed'}
                                  class:dark:bg-red-950={result.status === 'error' || result.status === 'failed'}
                                  class:dark:text-red-300={result.status === 'error' || result.status === 'failed'}
                                  class:dark:ring-red-500={result.status === 'error' || result.status === 'failed'}

                                  class:bg-blue-50={result.status === 'running'}
                                  class:text-blue-700={result.status === 'running'}
                                  class:ring-blue-600={result.status === 'running'}
                                  class:dark:bg-blue-950={result.status === 'running'}
                                  class:dark:text-blue-300={result.status === 'running'}
                                  class:dark:ring-blue-500={result.status === 'running'}

                                  class:bg-yellow-50={result.status === 'queued'}
                                  class:text-yellow-700={result.status === 'queued'}
                                  class:ring-yellow-600={result.status === 'queued'}
                                  class:dark:bg-yellow-950={result.status === 'queued'}
                                  class:dark:text-yellow-300={result.status === 'queued'}
                                  class:dark:ring-yellow-500={result.status === 'queued'}
                            >Status: {result.status}</span>

                            {#if result.execution_id}
                                <div class="relative group">
                                    <button class="inline-flex items-center p-1.5 rounded-lg text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors duration-150 cursor-pointer"
                                            aria-label="Click to copy execution ID"
                                            onclick={() => copyExecutionId(result.execution_id)}>
                                        <FileText class="w-4 h-4" />
                                    </button>
                                    <div class="absolute top-8 right-0 z-10 px-2 py-1 text-xs bg-neutral-800 dark:bg-neutral-200 text-white dark:text-neutral-800 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap">
                                        Execution ID:
                                        <br>{result.execution_id}
                                        <br><span class="text-xs opacity-75">Click to copy</span>
                                    </div>
                                </div>
                            {/if}
                        </div>

                        {#if result.stdout}
                            <div class="output-section">
                                <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1 uppercase tracking-wider">
                                    Output:</h4>
                                <div class="relative">
                                    <pre class="output-pre custom-scrollbar">{@html sanitizeOutput(ansiConverter.toHtml(result.stdout || ''))}</pre>
                                    <div class="absolute bottom-2 right-2 group">
                                        <button class="inline-flex items-center p-1.5 rounded-lg text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors duration-150 cursor-pointer opacity-70 hover:opacity-100"
                                                aria-label="Copy output to clipboard"
                                                onclick={() => copyOutput(result.stdout)}>
                                            <Copy class="w-4 h-4" />
                                        </button>
                                        <div class="absolute bottom-8 right-0 z-10 px-2 py-1 text-xs bg-neutral-800 dark:bg-neutral-200 text-white dark:text-neutral-800 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap">
                                            Copy output
                                        </div>
                                    </div>
                                </div>
                            </div>
                        {/if}

                        {#if result.stderr}
                            <div class="error-section">
                                <h4 class="text-xs font-medium text-red-700 dark:text-red-300 mb-1 uppercase tracking-wider">
                                    Errors:</h4>
                                <div class="relative">
                                    <div class="p-3 rounded-lg bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800">
                                        <pre class="text-xs text-red-600 dark:text-red-300 whitespace-pre-wrap break-words font-mono bg-transparent p-0 pr-8">{@html sanitizeOutput(ansiConverter.toHtml(result.stderr || ''))}</pre>
                                    </div>
                                    <div class="absolute bottom-2 right-2 group">
                                        <button class="inline-flex items-center p-1.5 rounded-lg text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-200 hover:bg-red-100 dark:hover:bg-red-900 transition-colors duration-150 cursor-pointer opacity-70 hover:opacity-100"
                                                aria-label="Copy error text to clipboard"
                                                onclick={() => copyErrors(result.stderr)}>
                                            <Copy class="w-4 h-4" />
                                        </button>
                                        <div class="absolute bottom-8 right-0 z-10 px-2 py-1 text-xs bg-neutral-800 dark:bg-neutral-200 text-white dark:text-neutral-800 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap">
                                            Copy errors
                                        </div>
                                    </div>
                                </div>
                            </div>
                        {/if}

                        {#if result.resource_usage}
                            <div class="p-3 rounded-lg bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 text-xs space-y-1">
                                <h4 class="text-xs font-medium text-blue-700 dark:text-blue-300 mb-2 uppercase tracking-wider">
                                    Resource Usage:</h4>
                                <div class="grid grid-cols-1 sm:grid-cols-3 gap-x-3 gap-y-1">
                                    <div class="flex flex-col">
                                        <span class="text-fg-muted dark:text-dark-fg-muted font-normal">CPU:</span>
                                        <span class="text-fg-default dark:text-dark-fg-default font-medium">
                                            {result.resource_usage.cpu_time_jiffies === 0 
                                                ? '< 10 m'
                                                : `${(result.resource_usage.cpu_time_jiffies * 10).toFixed(3)} m` ?? 'N/A'}
                                        </span>
                                    </div>
                                    <div class="flex flex-col">
                                        <span class="text-fg-muted dark:text-dark-fg-muted font-normal">Memory:</span>
                                        <span class="text-fg-default dark:text-dark-fg-default font-medium">
                                            {`${(result.resource_usage.peak_memory_kb / 1024).toFixed(3)} MiB` ?? 'N/A'}
                                        </span>
                                    </div>
                                    <div class="flex flex-col">
                                        <span class="text-fg-muted dark:text-dark-fg-muted font-normal">Time:</span>
                                        <span class="text-fg-default dark:text-dark-fg-default font-medium">
                                            {`${result.resource_usage.execution_time_wall_seconds.toFixed(3)} s` ?? 'N/A'}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        {/if}
                    </div>
                {:else}
                    <div class="flex items-center justify-center h-full text-center text-fg-muted dark:text-dark-fg-muted italic p-4">
                        Write some code and click "Run Script" to see the output.
                    </div>
                {/if}
            </div>
        </div>
    </div>

    <div class="editor-controls">
        <div class="flex flex-col space-y-3">
            <div class="flex items-center space-x-2 flex-wrap gap-y-2">
                <!-- Language Selector Dropdown -->
                <div class="relative">
                    <button onclick={() => showLangOptions = !showLangOptions}
                            disabled={!runtimesAvailable}
                            class="btn btn-secondary-outline btn-sm w-36 flex items-center justify-between text-left"
                            class:opacity-50={!runtimesAvailable}
                            class:cursor-not-allowed={!runtimesAvailable}>
                        <span class="capitalize truncate">{runtimesAvailable ? `${$selectedLang} ${$selectedVersion}` : "Unavailable"}</span>
                        <span class="ml-2 shrink-0 text-fg-muted dark:text-dark-fg-muted transform transition-transform" class:-rotate-180={showLangOptions}>
                            <ChevronDown class="w-5 h-5" />
                        </span>
                    </button>

                    {#if showLangOptions && runtimesAvailable}
                        <div transition:fly={{ y: -5, duration: 150 }}
                             class="absolute bottom-full mb-2 w-36 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-xl ring-1 ring-black/5 dark:ring-white/10 z-30">
                            <ul class="py-1" onmouseleave={() => hoveredLang = null}>
                                {#each Object.entries(supportedRuntimes) as [lang, langInfo] (lang)}
                                    <li class="relative" onmouseenter={() => hoveredLang = lang}>
                                        <div class="flex justify-between items-center w-full px-3 py-2 text-sm text-fg-default dark:text-dark-fg-default">
                                            <span class="capitalize font-medium">{lang}</span>
                                            <ChevronRight class="w-4 h-4 text-fg-muted dark:text-dark-fg-muted" />
                                        </div>

                                        {#if hoveredLang === lang && langInfo.versions.length > 0}
                                            <div class="absolute left-full top-0 -mt-1 ml-1 w-20 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-lg ring-1 ring-black/5 dark:ring-white/10 z-40"
                                                 transition:fly={{ x: 5, duration: 100 }}>
                                                <ul class="py-1 max-h-60 overflow-y-auto custom-scrollbar">
                                                    {#each langInfo.versions as version (version)}
                                                        <li>
                                                            <button onclick={() => { selectedLang.set(lang); selectedVersion.set(version); showLangOptions = false; hoveredLang = null; }}
                                                                    class="w-full text-left px-3 py-1.5 text-sm hover:bg-neutral-100 dark:hover:bg-neutral-700/60 transition-colors duration-100"
                                                                    class:text-primary={lang === $selectedLang && version === $selectedVersion}
                                                                    class:dark:text-primary-light={lang === $selectedLang && version === $selectedVersion}
                                                                    class:font-semibold={lang === $selectedLang && version === $selectedVersion}
                                                                    class:text-fg-default={lang !== $selectedLang || version !== $selectedVersion}
                                                                    class:dark:text-dark-fg-default={lang !== $selectedLang || version !== $selectedVersion}
                                                            >
                                                                {version}
                                                            </button>
                                                        </li>
                                                    {/each}
                                                </ul>
                                            </div>
                                        {/if}
                                    </li>
                                {/each}
                            </ul>
                        </div>
                    {/if}
                </div>
                <button class="btn btn-primary btn-sm flex-grow sm:flex-grow-0 min-w-[130px]" onclick={executeScript}
                        disabled={executing || !runtimesAvailable}>
                    <CirclePlay class="w-5 h-5" />
                    <span class="ml-1.5">{executing ? "Executing..." : "Run Script"}</span>
                </button>
                <button class="btn btn-secondary-outline btn-sm btn-icon ml-auto sm:ml-2"
                        onclick={toggleOptions}
                        aria-expanded={showOptions}
                        title={showOptions ? "Hide Options" : "Show Options"}>
                    <span class="sr-only">Toggle Script Options</span>
                    <div class="transition-transform duration-300 ease-out-expo" class:rotate-90={showOptions}>
                        <Settings class="w-5 h-5" />
                    </div>
                </button>
            </div>

            {#if showOptions}
                <div class="p-4 bg-bg-alt dark:bg-dark-bg-alt border border-border-default dark:border-dark-border-default rounded-lg flex space-x-4"
                     transition:slide={{ duration: 300, easing: (t) => 1 - Math.pow(1 - t, 3) }}>

                    <!-- Left Column: File Actions -->
                    <div class="w-1/2 space-y-3">
                        <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">
                            File Actions
                        </h4>
                        <div class="grid grid-cols-2 gap-2">
                            <button class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
                                    onclick={newScript} title="Start a new script">
                                <FilePlus class="w-4 h-4" /><span>New</span>
                            </button>
                            <button class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
                                    onclick={() => fileInput.click()} title="Upload a file">
                                <Upload class="w-4 h-4" /><span>Upload</span>
                            </button>
                            {#if authenticated}
                                <button class="btn btn-primary btn-sm inline-flex items-center justify-center space-x-1"
                                        onclick={saveScript} title="Save current script">
                                    <Save class="w-4 h-4" /><span>Save</span>
                                </button>
                            {/if}
                            <button class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
                                    onclick={exportScript} title="Download current script">
                                <Download class="w-4 h-4" /><span>Export</span>
                            </button>
                        </div>
                    </div>

                    <!-- Divider -->
                    <div class="border-l border-border-default dark:border-dark-border-default"></div>

                    <!-- Right Column: Saved Scripts -->
                    <div class="w-1/2 space-y-3">
                        {#if authenticated}
                            <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">
                                Saved Scripts
                            </h4>
                            <div>
                                <button class="btn btn-secondary-outline btn-sm w-full inline-flex items-center justify-center space-x-1.5"
                                        onclick={toggleSavedScripts}
                                        aria-expanded={showSavedScripts}
                                        title={showSavedScripts ? "Hide Saved Scripts" : "Show Saved Scripts"}>
                                    <List class="w-4 h-4" />
                                    <span>{showSavedScripts ? "Hide" : "Show"} Saved Scripts</span>
                                </button>
                            </div>
                            {#if showSavedScripts}
                                <div class="mt-2"
                                     transition:slide={{ duration: 200 }}>
                                    {#if savedScripts.length > 0}
                                        <div class="saved-scripts-container border border-border-default dark:border-dark-border-default rounded-lg bg-bg-default dark:bg-dark-bg-default shadow-inner">
                                            <ul class="divide-y divide-border-default dark:divide-dark-border-default">
                                                {#each savedScripts as savedItem, index (savedItem.id || index)}
                                                    <li class="flex items-center justify-between hover:bg-neutral-100 dark:hover:bg-neutral-700/50 text-sm group transition-colors duration-100">
                                                        <button class="flex-grow text-left px-3 py-2 text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light font-medium min-w-0"
                                                                onclick={() => loadScript(savedItem)}
                                                                title={`Load ${savedItem.name} (${savedItem.lang || 'python'} ${savedItem.lang_version || '3.11'})`}>
                                                            <div class="flex flex-col min-w-0">
                                                                <span class="truncate">{savedItem.name}</span>
                                                                <span class="text-xs text-fg-muted dark:text-dark-fg-muted font-normal capitalize">
                                                                    {savedItem.lang || 'python'} {savedItem.lang_version || '3.11'}
                                                                </span>
                                                            </div>
                                                        </button>
                                                        <button class="p-2 text-neutral-400 dark:text-neutral-500 hover:text-red-500 dark:hover:text-red-400 shrink-0 opacity-60 group-hover:opacity-100 transition-opacity duration-150 mr-1"
                                                                onclick={(e) => { e.stopPropagation(); deleteScript(savedItem.id); }}
                                                                title={`Delete ${savedItem.name}`}>
                                                            <span class="sr-only">Delete</span>
                                                            <Trash2 class="w-4 h-4" />
                                                        </button>
                                                    </li>
                                                {/each}
                                            </ul>
                                        </div>
                                    {:else}
                                        <p class="p-4 text-xs text-fg-muted dark:text-dark-fg-muted italic text-center border border-border-default dark:border-dark-border-default rounded-lg">
                                            No saved scripts yet.</p>
                                    {/if}
                                </div>
                            {/if}
                        {:else}
                             <div class="flex flex-col items-center justify-center h-full text-center">
                                 <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider mb-2">
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
