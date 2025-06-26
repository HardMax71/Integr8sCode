<script>
    import {onDestroy, onMount} from "svelte";
    import {fade, fly, slide} from "svelte/transition";
    import {get, writable} from "svelte/store";
    import axios from "axios";
    import {authToken, logout as authLogout} from "../stores/auth.js";
    import {addNotification} from "../stores/notifications.js";
    import Spinner from "../components/Spinner.svelte";
    import {navigate} from "svelte-routing";
    import {Compartment, EditorState} from "@codemirror/state";
    import {EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers} from "@codemirror/view";
    import {defaultKeymap, history, historyKeymap, indentWithTab} from "@codemirror/commands";
    import {python} from "@codemirror/lang-python";
    import {oneDark} from "@codemirror/theme-one-dark";
import {githubLight} from "@uiw/codemirror-theme-github";
    import {bracketMatching} from "@codemirror/language";
    import {autocompletion, completionKeymap} from "@codemirror/autocomplete";
    import {theme as appTheme} from "../stores/theme.js";

    let themeCompartment = new Compartment();

    function createPersistentStore(key, startValue) {
        if (typeof localStorage === 'undefined') {
            const store = writable(startValue);
            return {subscribe: store.subscribe, set: store.set};
        }
        const storedValue = localStorage.getItem(key);
        const store = writable(storedValue ? JSON.parse(storedValue) : startValue);
        store.subscribe(value => {
            localStorage.setItem(key, JSON.stringify(value));
        });
        return store;
    }

    let script = createPersistentStore("script", "# Welcome to Integr8sCode!\n\nprint('Hello, Kubernetes!')");
    let executing = false;
    let result = null;
    let editorView = null;
    let editorContainer;
    let k8sLimits = null;
    let pythonVersion = writable("3.9");
    let supportedPythonVersions = [];
    let showLimits = false;
    let showOptions = false;
    let showSavedScripts = false;

    let isAuthenticated = false;
    let savedScripts = [];
    let scriptName = createPersistentStore("scriptName", "");
    let currentScriptId = createPersistentStore("currentScriptId", null);

    let fileInput;
    let apiError = null;

    const resourceIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l4-4z"></path></svg>`;
    const chevronDownIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>`;
    const chevronUpIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"></path></svg>`;
    const cpuIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path></svg>`;
    const memoryIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path></svg>`;
    const timeoutIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
    const playIcon = `<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd" /></svg>`;
    const settingsIcon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>`;
    const newFileIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>`;
    const uploadIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>`;
    const exportIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>`;
    const saveIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"></path></svg>`;
    const listIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16"></path></svg>`;
    const trashIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`;
    const idIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>`;
    const copyIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"></path></svg>`;

    let unsubscribeAuth;
    let unsubscribeTheme;

    onMount(async () => {
        unsubscribeAuth = authToken.subscribe(token => {
            const wasAuthenticated = isAuthenticated;
            isAuthenticated = !!token;
            if (!wasAuthenticated && isAuthenticated && editorView) {
                loadSavedScripts();
            } else if (wasAuthenticated && !isAuthenticated) {
                savedScripts = [];
                showSavedScripts = false;
                currentScriptId.set(null);
                scriptName.set("");
            }
        });

        try {
            const limitsResponse = await axios.get(`/api/v1/k8s-limits`);
            k8sLimits = limitsResponse.data;
            supportedPythonVersions = k8sLimits?.supported_python_versions || ["3.9", "3.10", "3.11"];
            if (!supportedPythonVersions.includes(get(pythonVersion))) {
                pythonVersion.set(supportedPythonVersions[0] || "3.9");
            }
        } catch (err) {
            apiError = "Failed to fetch resource limits.";
            addNotification(apiError, "error");
            console.error("Error fetching K8s limits:", err);
            supportedPythonVersions = ["3.9", "3.10", "3.11"];
        }

        initializeEditor(get(appTheme));

        unsubscribeTheme = appTheme.subscribe(currentTheme => {
            if (editorView) {
                const newThemeExtension = currentTheme === 'dark' ? oneDark : githubLight;
                editorView.dispatch({
                    effects: themeCompartment.reconfigure(newThemeExtension)
                });
            }
        });

        if (isAuthenticated) {
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
    });

    function getStaticExtensions() {
        return [
            lineNumbers(),
            highlightActiveLineGutter(),
            highlightActiveLine(),
            history(),
            bracketMatching(),
            autocompletion(),
            EditorState.allowMultipleSelections.of(true),
            keymap.of([
                ...defaultKeymap,
                ...historyKeymap,
                ...completionKeymap,
                indentWithTab
            ]),
            python(),
            EditorView.lineWrapping,
            EditorView.updateListener.of(update => {
                if (update.docChanged) {
                    script.set(update.state.doc.toString());
                }
            }),
        ];
    }

    function initializeEditor(currentTheme) {
        if (!editorContainer || editorView) return;

        const initialThemeExtension = currentTheme === 'dark' ? oneDark : githubLight;

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
            addNotification("Failed to load code editor.", "error");
        }
    }

    async function executeScript() {
        executing = true;
        apiError = null;
        result = null;
        const scriptValue = get(script);
        const pythonVersionValue = get(pythonVersion);
        let executionId = null;

        try {
            const executeResponse = await axios.post(`/api/v1/execute`, {
                script: scriptValue,
                python_version: pythonVersionValue
            });
            executionId = executeResponse.data.execution_id;
            result = {status: 'running', execution_id: executionId};

            const pollInterval = 1000;
            const maxAttempts = (k8sLimits?.execution_timeout || 5) + 10;
            let attempts = 0;

            while (attempts < maxAttempts && (result?.status === 'queued' || result?.status === 'running')) {
                await new Promise(resolve => setTimeout(resolve, pollInterval));
                attempts++;
                try {
                    const resultResponse = await axios.get(`/api/v1/result/${executionId}`);
                    result = resultResponse.data;

                    if (result.status === 'completed' || result.status === 'error') {
                        break;
                    }
                } catch (pollError) {
                    console.error("Polling error:", pollError);
                    if (pollError.response?.status === 404) {
                        apiError = `Execution ID ${executionId} not found. It might have expired or never existed.`;
                        result = {status: 'error', errors: apiError, execution_id: executionId};
                        addNotification(apiError, "error");
                        break;
                    } else if (pollError.response) {
                        apiError = `Error polling for results (Status ${pollError.response.status}).`;
                        result = {status: 'error', errors: apiError, execution_id: executionId};
                        addNotification(apiError, "warning");

                    } else {
                        apiError = 'Network error while polling for results.';
                        result = {status: 'error', errors: apiError, execution_id: executionId};
                        addNotification(apiError, "warning");
                    }

                    if (result.status === 'error') {
                        break;
                    }
                    break;
                }
            }

            if (result?.status !== 'completed' && result?.status !== 'error') {
                const timeoutMessage = `Execution timed out after ${attempts} seconds waiting for a final status.`;
                result = {status: 'error', errors: timeoutMessage, execution_id: executionId};
                addNotification(timeoutMessage, 'warning');
            }

        } catch (err) {
            apiError = err.response?.data?.detail || "Error initiating script execution.";
            addNotification(apiError, "error");
            result = {status: 'error', errors: apiError, execution_id: executionId};
            console.error("Error executing script:", err.response || err);
        } finally {
            executing = false;
        }
    }

    async function loadSavedScripts() {
        if (!isAuthenticated) return;
        const authTokenValue = get(authToken);
        try {
            const response = await axios.get(`/api/v1/scripts`, {
                headers: {Authorization: `Bearer ${authTokenValue}`},
            });
            savedScripts = response.data || [];
        } catch (err) {
            console.error("Error loading saved scripts:", err);
            addNotification("Failed to load saved scripts. You might need to log in again.", "error");
            if (err.response?.status === 401) {
                handleLogout();
            }
        }
    }

    function loadScript(scriptData) {
        if (!editorView) return;
        script.set(scriptData.script);
        scriptName.set(scriptData.name);
        currentScriptId.set(scriptData.id);
        editorView.dispatch({
            changes: {
                from: 0,
                to: editorView.state.doc.length,
                insert: scriptData.script,
            },
            selection: {anchor: 0}
        });
        addNotification(`Loaded script: ${scriptData.name}`, "info");
        showSavedScripts = false;
        showOptions = false;
        result = null;
        apiError = null;
    }

    async function saveScript() {
        if (!isAuthenticated) {
            addNotification("Please log in to save scripts.", "warning");
            return;
        }
        const nameValue = get(scriptName);
        if (!nameValue.trim()) {
            addNotification("Please provide a name for your script.", "warning");
            return;
        }
        const scriptValue = get(script);
        const authTokenValue = get(authToken);
        const currentIdValue = get(currentScriptId);
        let operation = currentIdValue ? 'update' : 'create';

        try {
            let response;
            if (operation === 'update') {
                response = await axios.put(
                    `/api/v1/scripts/${currentIdValue}`,
                    {name: nameValue, script: scriptValue},
                    {headers: {Authorization: `Bearer ${authTokenValue}`}}
                );
                addNotification("Script updated successfully.", "success");
            } else {
                response = await axios.post(
                    `/api/v1/scripts`,
                    {name: nameValue, script: scriptValue},
                    {headers: {Authorization: `Bearer ${authTokenValue}`}}
                );
                currentScriptId.set(response.data.id);
                addNotification("Script saved successfully.", "success");
            }
            await loadSavedScripts();
        } catch (err) {
            console.error(`Error ${operation === 'update' ? 'updating' : 'saving'} script:`, err.response || err);
            addNotification(`Failed to ${operation} script. Please try again.`, "error");
            if (err.response?.status === 401) {
                handleLogout();
            }
        }
    }

    async function deleteScript(scriptIdToDelete) {
        if (!isAuthenticated) return;
        const scriptToDelete = savedScripts.find(s => s.id === scriptIdToDelete);
        const confirmMessage = scriptToDelete
            ? `Are you sure you want to delete "${scriptToDelete.name}"?`
            : "Are you sure you want to delete this script?";

        if (!confirm(confirmMessage)) return;

        const authTokenValue = get(authToken);
        try {
            await axios.delete(`/api/v1/scripts/${scriptIdToDelete}`, {
                headers: {Authorization: `Bearer ${authTokenValue}`},
            });
            addNotification("Script deleted successfully.", "success");
            if (get(currentScriptId) === scriptIdToDelete) {
                newScript();
            }
            await loadSavedScripts();
        } catch (err) {
            console.error("Error deleting script:", err.response || err);
            addNotification("Failed to delete script.", "error");
            if (err.response?.status === 401) {
                handleLogout();
            }
        }
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
        addNotification("New script started.", "info");
    }

    function exportScript() {
        const scriptValue = get(script);
        const blob = new Blob([scriptValue], {type: "text/plain;charset=utf-8"});
        const url = URL.createObjectURL(blob);
        let filename = get(scriptName).trim() || "script.py";
        if (!filename.toLowerCase().endsWith(".py")) {
            filename += ".py";
        }
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function handleFileUpload(event) {
        const file = event.target.files[0];
        if (!file) return;
        if (!file.name.toLowerCase().endsWith(".py")) {
            addNotification("Only .py files are allowed.", "error");
            return;
        }
        const reader = new FileReader();
        reader.onload = e => {
            const text = e.target.result;
            if (editorView) {
                newScript();
                script.set(text);
                scriptName.set(file.name);
                editorView.dispatch({
                    changes: {from: 0, to: editorView.state.doc.length, insert: text},
                    selection: {anchor: 0}
                });
                addNotification(`Loaded script from ${file.name}`, "info");
            }
        };
        reader.onerror = () => {
            addNotification("Failed to read the selected file.", "error");
        };
        reader.readAsText(file);
        event.target.value = null;
    }

    function handleLogout() {
        authLogout();
        navigate("/login");
        addNotification("You have been logged out.", "info");
    }

    function toggleLimits() {
        showLimits = !showLimits;
    }

    function toggleOptions() {
        showOptions = !showOptions;
        if (!showOptions) showSavedScripts = false;
    }

    function toggleSavedScripts() {
        showSavedScripts = !showSavedScripts;
        if (showSavedScripts && isAuthenticated) {
            loadSavedScripts();
        }
    }

    async function copyExecutionId(executionId) {
        try {
            await navigator.clipboard.writeText(executionId);
            addNotification("Execution ID copied to clipboard", "success");
        } catch (err) {
            console.error("Failed to copy execution ID:", err);
            addNotification("Failed to copy execution ID", "error");
        }
    }

    async function copyOutput(output) {
        try {
            await navigator.clipboard.writeText(output);
            addNotification("Output copied to clipboard", "success");
        } catch (err) {
            console.error("Failed to copy output:", err);
            addNotification("Failed to copy output", "error");
        }
    }

    async function copyErrors(errors) {
        try {
            await navigator.clipboard.writeText(errors);
            addNotification("Error text copied to clipboard", "success");
        } catch (err) {
            console.error("Failed to copy errors:", err);
            addNotification("Failed to copy errors", "error");
        }
    }
</script>

<input type="file" accept=".py,text/x-python" bind:this={fileInput} class="hidden"/>

<div class="editor-grid-container space-y-4 md:space-y-0 md:gap-6" in:fade={{ duration: 300 }}>
    <header class="editor-header flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h2 class="text-xl sm:text-2xl font-semibold text-fg-default dark:text-dark-fg-default whitespace-nowrap">
            Python Code Editor
        </h2>
        {#if k8sLimits}
            <div class="relative flex-shrink-0">
                <button class="btn btn-secondary-outline btn-sm inline-flex items-center space-x-1.5 w-full sm:w-auto justify-center"
                        on:click={toggleLimits} aria-expanded={showLimits}>
                    {@html resourceIcon}
                    <span>Resource Limits</span>
                    {#if showLimits} {@html chevronUpIcon} {:else} {@html chevronDownIcon} {/if}
                </button>
                {#if showLimits}
                    <div class="absolute right-0 mt-2 w-64 sm:w-72 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-xl ring-1 ring-black ring-opacity-5 dark:ring-white dark:ring-opacity-10 p-5 z-20 border border-border-default dark:border-dark-border-default"
                         transition:fly={{ y: -10, duration: 200 }}>
                        <div class="space-y-4">
                            <div class="flex items-center justify-between text-sm">
                                <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center"><span
                                        class="mr-2">{@html cpuIcon}</span>CPU Limit</span>
                                <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums">{k8sLimits.cpu_limit}</span>
                            </div>
                            <div class="flex items-center justify-between text-sm">
                                <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center"><span
                                        class="mr-2">{@html memoryIcon}</span>Memory Limit</span>
                                <span class="font-semibold text-fg-default dark:text-dark-fg-default tabular-nums">{k8sLimits.memory_limit}</span>
                            </div>
                            <div class="flex items-center justify-between text-sm">
                                <span class="text-fg-muted dark:text-dark-fg-muted inline-flex items-center"><span
                                        class="mr-2">{@html timeoutIcon}</span>Timeout</span>
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
    </header>

    <div class="editor-main-code rounded-lg overflow-hidden shadow-md border border-border-default dark:border-dark-border-default">
        <div bind:this={editorContainer} class="editor-wrapper h-full w-full">
            {#if !editorView}
                <div class="flex items-center justify-center h-full p-4 text-center text-fg-muted dark:text-dark-fg-muted">
                    <Spinner/>
                    <span class="ml-2">Loading Editor...</span>
                </div>
            {/if}
        </div>
    </div>

    <div class="editor-main-output">
        <div class="output-container flex flex-col h-full">
            <h3 class="text-base font-medium text-fg-default dark:text-dark-fg-default mb-3 border-b border-border-default dark:border-dark-border-default pb-3 flex-shrink-0">
                Execution Output
            </h3>
            <div class="output-content flex-grow overflow-auto pr-2 text-sm custom-scrollbar">
                {#if executing}
                    <div class="flex flex-col items-center justify-center h-full text-center p-4 animate-fadeIn">
                        <Spinner/>
                        <p class="mt-3 text-sm font-medium text-primary dark:text-primary-light">Executing script...</p>
                    </div>
                {:else if result}
                    <div class="space-y-5 animate-flyIn">
                        <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs">
                            <span class="inline-flex items-center rounded-md px-2 py-1 font-medium ring-1 ring-inset whitespace-nowrap"
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
                                    <button class="inline-flex items-center p-1.5 rounded-md text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors duration-150 cursor-pointer"
                                            title="Click to copy execution ID"
                                            on:click={() => copyExecutionId(result.execution_id)}>
                                        {@html idIcon}
                                    </button>
                                    <div class="absolute top-8 right-0 z-10 px-2 py-1 text-xs bg-neutral-800 dark:bg-neutral-200 text-white dark:text-neutral-800 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap">
                                        Execution ID:
                                        <br>{result.execution_id}
                                        <br><span class="text-xs opacity-75">Click to copy</span>
                                    </div>
                                </div>
                            {/if}
                        </div>

                        {#if result.output}
                            <div class="output-section">
                                <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1 uppercase tracking-wider">
                                    Output:</h4>
                                <div class="relative">
                                    <pre class="output-pre custom-scrollbar">{result.output || ''}</pre>
                                    <div class="absolute bottom-2 right-2 group">
                                        <button class="inline-flex items-center p-1.5 rounded-md text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors duration-150 cursor-pointer opacity-70 hover:opacity-100"
                                                title="Copy output to clipboard"
                                                on:click={() => copyOutput(result.output)}>
                                            {@html copyIcon}
                                        </button>
                                        <div class="absolute bottom-8 right-0 z-10 px-2 py-1 text-xs bg-neutral-800 dark:bg-neutral-200 text-white dark:text-neutral-800 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap">
                                            Copy output
                                        </div>
                                    </div>
                                </div>
                            </div>
                        {/if}

                        {#if result.errors}
                            <div class="error-section">
                                <h4 class="text-xs font-medium text-red-700 dark:text-red-300 mb-1 uppercase tracking-wider">
                                    Errors:</h4>
                                <div class="relative">
                                    <div class="p-3 rounded-md bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800">
                                        <pre class="text-xs text-red-600 dark:text-red-300 whitespace-pre-wrap break-words font-mono bg-transparent p-0 pr-8">{result.errors}</pre>
                                    </div>
                                    <div class="absolute bottom-2 right-2 group">
                                        <button class="inline-flex items-center p-1.5 rounded-md text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-200 hover:bg-red-100 dark:hover:bg-red-900 transition-colors duration-150 cursor-pointer opacity-70 hover:opacity-100"
                                                title="Copy error text to clipboard"
                                                on:click={() => copyErrors(result.errors)}>
                                            {@html copyIcon}
                                        </button>
                                        <div class="absolute bottom-8 right-0 z-10 px-2 py-1 text-xs bg-neutral-800 dark:bg-neutral-200 text-white dark:text-neutral-800 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap">
                                            Copy errors
                                        </div>
                                    </div>
                                </div>
                            </div>
                        {/if}

                        {#if result.resource_usage}
                            <div class="p-3 rounded-md bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 text-xs space-y-1">
                                <h4 class="text-xs font-medium text-blue-700 dark:text-blue-300 mb-2 uppercase tracking-wider">
                                    Resource Usage:</h4>
                                <div class="grid grid-cols-1 sm:grid-cols-3 gap-x-3 gap-y-1">
                                    <div class="flex flex-col">
                                        <span class="text-fg-muted dark:text-dark-fg-muted font-normal">CPU:</span>
                                        <span class="text-fg-default dark:text-dark-fg-default font-medium">{result.resource_usage.cpu_usage ?? 'N/A'} m</span>
                                    </div>
                                    <div class="flex flex-col">
                                        <span class="text-fg-muted dark:text-dark-fg-muted font-normal">Memory:</span>
                                        <span class="text-fg-default dark:text-dark-fg-default font-medium">{result.resource_usage.memory_usage ?? 'N/A'} Mi</span>
                                    </div>
                                    <div class="flex flex-col">
                                        <span class="text-fg-muted dark:text-dark-fg-muted font-normal">Time:</span>
                                        <span class="text-fg-default dark:text-dark-fg-default font-medium">{result.resource_usage.execution_time ?? 'N/A'} s</span>
                                    </div>
                                </div>
                            </div>
                        {/if}
                    </div>
                {:else}
                    <div class="flex items-center justify-center h-full text-center text-fg-muted dark:text-dark-fg-muted italic p-4">
                        Write some Python code and click "Run Script" to see the output.
                    </div>
                {/if}
            </div>
        </div>
    </div>

    <div class="editor-controls">
        <div class="flex flex-col space-y-3">
            <div class="flex items-center space-x-2 flex-wrap gap-y-2">
                <select bind:value={$pythonVersion} class="form-select select-sm flex-shrink-0 w-auto !py-1.5 border-border-input dark:border-dark-border-input bg-bg-alt dark:bg-dark-bg-alt dark:text-dark-fg-default focus:border-primary dark:focus:border-primary focus:ring focus:ring-focus-ring dark:focus:ring-dark-focus-ring focus:ring-opacity-50 shadow-sm transition-colors duration-150">
                    {#each supportedPythonVersions as version}
                        <option value={version}>Python {version}</option>
                    {/each}
                </select>
                <button class="btn btn-primary flex-grow sm:flex-grow-0 min-w-[130px]" on:click={executeScript}
                        disabled={executing}>
                    {@html playIcon}
                    <span class="ml-1.5">{executing ? "Executing..." : "Run Script"}</span>
                </button>
                <button class="btn btn-secondary-outline btn-sm btn-icon ml-auto sm:ml-2"
                        on:click={toggleOptions}
                        aria-expanded={showOptions}
                        title={showOptions ? "Hide Options" : "Show Options"}>
                    <span class="sr-only">Toggle Script Options</span>
                    <div class="transition-transform duration-300 ease-out-expo" class:rotate-90={showOptions}>
                        {@html settingsIcon}
                    </div>
                </button>
            </div>

            {#if showOptions}
                <div class="p-4 bg-bg-alt dark:bg-dark-bg-alt border border-border-default dark:border-dark-border-default rounded-lg space-y-4"
                     transition:slide={{ duration: 300, easing: (t) => 1 - Math.pow(1 - t, 3) }}>
                    <div>
                        <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-2 uppercase tracking-wider">
                            File Actions</h4>
                        <div class="grid grid-cols-3 gap-2">
                            <button class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1.5"
                                    on:click={newScript} title="Start a new script">
                                {@html newFileIcon}<span>New</span>
                            </button>
                            <button class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1.5"
                                    on:click={() => fileInput.click()} title="Upload a .py file">
                                {@html uploadIcon}<span>Upload</span>
                            </button>
                            <button class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1.5"
                                    on:click={exportScript} title="Download current script">
                                {@html exportIcon}<span>Export</span>
                            </button>
                        </div>
                    </div>

                    {#if isAuthenticated}
                        <div class="pt-4 border-t border-border-default dark:border-dark-border-default">
                            <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-2 uppercase tracking-wider">
                                Saved Scripts</h4>
                            <div class="flex items-stretch space-x-2">
                                <label for="scriptNameInput" class="sr-only">Script Name</label>
                                <input id="scriptNameInput" type="text" class="form-input input-sm flex-grow min-w-0"
                                       placeholder="Script Name (e.g., my_script.py)" bind:value={$scriptName}/>
                                <button class="btn btn-primary btn-sm flex-shrink-0 inline-flex items-center"
                                        on:click={saveScript} title="Save current script">
                                    {@html saveIcon}<span class="ml-1.5 hidden sm:inline">Save</span>
                                </button>
                                <button class="btn btn-secondary-outline btn-sm btn-icon flex-shrink-0"
                                        on:click={toggleSavedScripts}
                                        aria-expanded={showSavedScripts}
                                        title={showSavedScripts ? "Hide Saved Scripts" : "Show Saved Scripts"}>
                                    <span class="sr-only">Toggle Saved Scripts List</span>
                                    {@html listIcon}
                                </button>
                            </div>
                            {#if showSavedScripts}
                                <div class="mt-3 max-h-48 overflow-y-auto border border-border-default dark:border-dark-border-default rounded-md bg-bg-default dark:bg-dark-bg-default shadow-inner custom-scrollbar"
                                     transition:slide={{ duration: 200 }}>
                                    {#if savedScripts.length > 0}
                                        <ul class="divide-y divide-border-default dark:divide-dark-border-default">
                                            {#each savedScripts as savedItem (savedItem.id)}
                                                <li class="flex items-center justify-between hover:bg-neutral-100 dark:hover:bg-neutral-700/50 text-sm group transition-colors duration-100">
                                                    <button class="flex-grow text-left px-3 py-2 text-fg-default dark:text-dark-fg-default hover:text-primary dark:hover:text-primary-light truncate font-medium"
                                                            on:click={() => loadScript(savedItem)}
                                                            title={`Load ${savedItem.name}`}>
                                                        {savedItem.name}
                                                    </button>
                                                    <button class="p-2 text-neutral-400 dark:text-neutral-500 hover:text-red-500 dark:hover:text-red-400 flex-shrink-0 opacity-60 group-hover:opacity-100 transition-opacity duration-150 mr-1"
                                                            on:click|stopPropagation={() => deleteScript(savedItem.id)}
                                                            title={`Delete ${savedItem.name}`}>
                                                        <span class="sr-only">Delete</span>
                                                        {@html trashIcon}
                                                    </button>
                                                </li>
                                            {/each}
                                        </ul>
                                    {:else}
                                        <p class="p-4 text-xs text-fg-muted dark:text-dark-fg-muted italic text-center">
                                            You have no saved scripts.</p>
                                    {/if}
                                </div>
                            {/if}
                        </div>
                    {/if}
                </div>
            {/if}
        </div>
    </div>
</div>


<style lang="postcss">
    :root {
        --font-mono: theme('fontFamily.mono');
        --cm-background: theme('colors.bg-alt');
        --cm-foreground: theme('colors.fg-default');
        --cm-gutter-background: theme('colors.bg-default');
        --cm-gutter-foreground: theme('colors.neutral.400');
        --cm-gutter-border: theme('colors.border-default');
        --cm-active-gutter-background: theme('colors.neutral.100');
    }

    .editor-grid-container {
        display: grid;
        grid-template-columns: minmax(0, 1fr);
        grid-template-rows: auto auto minmax(300px, 50vh) minmax(200px, 30vh) auto;
        gap: 1rem;
        width: 100%;
    }

    .editor-header {
        grid-row: 1 / 2;
    }

    .editor-controls {
        grid-row: 2 / 3;
    }

    .editor-main-code {
        grid-row: 3 / 4;
        min-height: 0;
    }
    
    .editor-main-output {
        grid-row: 4 / 5;
        min-height: 0;
        display: flex;
    }

    @media (min-width: 768px) {
        .editor-grid-container {
            grid-template-columns: minmax(0, 1.85fr) minmax(0, 1fr);
            grid-template-rows: auto minmax(400px, 65vh) auto;
            gap: 1.5rem;
        }

        .editor-header {
            grid-column: 1 / -1;
            grid-row: 1 / 2;
        }

        .editor-main-code {
            grid-column: 1 / 2;
            grid-row: 2 / 3;
        }

        .editor-main-output {
            grid-column: 2 / 3;
            grid-row: 2 / 3;
        }

        .editor-controls {
            grid-column: 1 / -1;
            grid-row: 3 / 4;
        }
    }

    .output-container {
        @apply bg-bg-alt dark:bg-dark-bg-alt border border-border-default dark:border-dark-border-default rounded-lg p-4 w-full overflow-hidden shadow-sm;
    }

    .output-content, .output-pre, .custom-scrollbar {
        scrollbar-width: thin;
        scrollbar-color: theme('colors.neutral.400') theme('colors.neutral.200');
    }

    .output-pre {
        @apply bg-bg-default dark:bg-dark-bg-default p-3 rounded border border-border-default dark:border-dark-border-default text-xs font-mono whitespace-pre-wrap break-words max-h-[40vh] overflow-auto;
        padding-right: 3rem; /* Space for copy button */
    }

    .output-section .relative {
        overflow: visible; /* Ensure copy button is visible */
    }

    /* Ensure copy buttons are above scrollbars */
    .output-section .group,
    .relative .group {
        z-index: 10;
    }

    .select-sm {
        @apply !text-xs !py-1.5 pl-2 pr-8;
    }

    .input-sm {
        @apply !text-xs !py-1.5 px-2;
    }

    .editor-controls .btn {
        @apply flex-shrink-0;
    }

    .editor-wrapper ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }

    .editor-wrapper ::-webkit-scrollbar-track {
        @apply bg-neutral-200 dark:bg-neutral-700 rounded-b-lg;
    }

    .editor-wrapper ::-webkit-scrollbar-thumb {
        @apply bg-neutral-400 dark:bg-neutral-500 rounded;
    }

    .editor-wrapper ::-webkit-scrollbar-thumb:hover {
        @apply bg-neutral-500 dark:bg-neutral-400;
    }

    .output-content::-webkit-scrollbar,
    .output-pre::-webkit-scrollbar,
    .custom-scrollbar::-webkit-scrollbar {
        width: 6px;
        height: 6px;
    }

    .output-content::-webkit-scrollbar-track,
    .output-pre::-webkit-scrollbar-track,
    .custom-scrollbar::-webkit-scrollbar-track {
        @apply bg-neutral-100 dark:bg-neutral-800 rounded;
        margin-right: 2px;
    }

    .output-content::-webkit-scrollbar-thumb,
    .output-pre::-webkit-scrollbar-thumb,
    .custom-scrollbar::-webkit-scrollbar-thumb {
        @apply bg-neutral-300 dark:bg-neutral-600 rounded;
    }

    .output-content::-webkit-scrollbar-thumb:hover,
    .output-pre::-webkit-scrollbar-thumb:hover,
    .custom-scrollbar::-webkit-scrollbar-thumb:hover {
        @apply bg-neutral-400 dark:bg-neutral-500;
    }

</style>