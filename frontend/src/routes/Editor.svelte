<script>
    import {onMount} from "svelte";
    import {fade, fly, slide} from "svelte/transition";
    import {get, writable} from "svelte/store";
    import axios from "axios";
    import {authToken} from "../stores/auth.js";
    import {addNotification} from "../stores/notifications.js";
    import Spinner from "../components/Spinner.svelte";
    import {backendUrl} from "../config.js";

    import {EditorState} from "@codemirror/state";
    import {EditorView, keymap, lineNumbers} from "@codemirror/view";
    import {defaultKeymap} from "@codemirror/commands";
    import {python} from "@codemirror/lang-python";
    import {oneDark} from "@codemirror/theme-one-dark";
    import {navigate} from "svelte-routing";

    function createPersistentStore(key, startValue) {
        const storedValue = localStorage.getItem(key);
        const store = writable(storedValue ? JSON.parse(storedValue) : startValue);
        store.subscribe(value => {
            localStorage.setItem(key, JSON.stringify(value));
        });
        return store;
    }

    let script = createPersistentStore("script", "");
    let executing = false;
    let error = "";
    let result = null;
    let editor;
    let k8sLimits = null;
    let pythonVersion = writable("3.9");
    let supportedPythonVersions = [];
    let showLimits = false;
    let showOptions = false;

    let isAuthenticated = false;
    let savedScripts = [];
    let showSavedScripts = false;
    let scriptName = "";
    let currentScriptId = null;

    // For file upload
    let fileInput;

    authToken.subscribe(token => {
        isAuthenticated = !!token;
    });

    onMount(async () => {
        try {
            const limitsResponse = await axios.get(`${backendUrl}/api/v1/k8s-limits`);
            k8sLimits = limitsResponse.data;
            supportedPythonVersions = k8sLimits.supported_python_versions;
        } catch (err) {
            console.error("Error fetching K8s limits:", err);
            addNotification("Failed to fetch resource limits.", "error");
        }

        const startState = EditorState.create({
            doc: get(script),
            extensions: [
                keymap.of(defaultKeymap),
                python(),
                oneDark,
                lineNumbers(),
                EditorView.updateListener.of(update => {
                    if (update.docChanged) {
                        script.set(update.state.doc.toString());
                    }
                }),
            ],
        });

        editor = new EditorView({
            state: startState,
            parent: document.getElementById("editor-container"),
        });

        if (isAuthenticated) {
            await loadSavedScripts();
        }
    });

    async function executeScript() {
        executing = true;
        error = "";
        result = null;
        const scriptValue = get(script);
        const pythonVersionValue = get(pythonVersion);
        try {
            const executeResponse = await axios.post(
                `${backendUrl}/api/v1/execute`,
                {script: scriptValue, python_version: pythonVersionValue}
            );
            const executionId = executeResponse.data.execution_id;
            while (true) {
                const resultResponse = await axios.get(
                    `${backendUrl}/api/v1/result/${executionId}`
                );
                if (
                    resultResponse.data.status === "completed" ||
                    resultResponse.data.status === "failed"
                ) {
                    console.log("Full response:", resultResponse.data);
                    result = resultResponse.data;
                    break;
                }
                await new Promise(resolve => setTimeout(resolve, 1000));
            }
        } catch (err) {
            error = err.response?.data?.detail || "An error occurred while executing the script.";
            console.error("Error executing script:", err);
        } finally {
            executing = false;
        }
    }

    function exportScript() {
        const blob = new Blob([get(script)], {type: "text/plain"});
        const url = URL.createObjectURL(blob);
        let filename = scriptName ? scriptName : "script.py";
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

    function toggleLimits() {
        showLimits = !showLimits;
    }

    async function saveScript() {
        if (!scriptName.trim()) {
            addNotification("Please provide a name for your script.", "warning");
            return;
        }
        const scriptValue = get(script);
        const authTokenValue = get(authToken);
        try {
            if (currentScriptId) {
                await axios.put(
                    `${backendUrl}/api/v1/scripts/${currentScriptId}`,
                    {name: scriptName, script: scriptValue},
                    {headers: {Authorization: `Bearer ${authTokenValue}`}}
                );
                addNotification("Script updated successfully.", "success");
            } else {
                const response = await axios.post(
                    `${backendUrl}/api/v1/scripts`,
                    {name: scriptName, script: scriptValue},
                    {headers: {Authorization: `Bearer ${authTokenValue}`}}
                );
                currentScriptId = response.data.id;
                addNotification("Script saved successfully.", "success");
            }
            await loadSavedScripts();
        } catch (err) {
            console.error("Error saving script:", err);
            addNotification("Failed to save script.", "error");
        }
    }

    function logout() {
        authToken.set(null);
        navigate("/login");
    }

    async function loadSavedScripts() {
        const authTokenValue = get(authToken);
        try {
            const response = await axios.get(`${backendUrl}/api/v1/scripts`, {
                headers: {Authorization: `Bearer ${authTokenValue}`},
            });
            savedScripts = response.data;
        } catch (err) {
            console.error("Error loading saved scripts:", err);
            addNotification("Failed to load saved scripts. Logging out...", "error");
            logout();
        }
    }

    function toggleSavedScripts() {
        showSavedScripts = !showSavedScripts;
        if (showSavedScripts && isAuthenticated) {
            loadSavedScripts();
        }
    }

    function loadScript(scriptData) {
        script.set(scriptData.script);
        scriptName = scriptData.name;
        currentScriptId = scriptData.id;
        editor.dispatch({
            changes: {
                from: 0,
                to: editor.state.doc.length,
                insert: scriptData.script,
            },
        });
        addNotification(`Loaded script: ${scriptData.name}`, "info");
        showSavedScripts = false;
    }

    function newScript() {
        script.set("");
        scriptName = "";
        currentScriptId = null;
        editor.dispatch({
            changes: {from: 0, to: editor.state.doc.length, insert: ""},
        });
    }

    async function deleteScript(scriptId) {
        const confirmDelete = confirm("Are you sure you want to delete this script?");
        if (!confirmDelete) return;
        const authTokenValue = get(authToken);
        try {
            await axios.delete(`${backendUrl}/api/v1/scripts/${scriptId}`, {
                headers: {Authorization: `Bearer ${authTokenValue}`},
            });
            addNotification("Script deleted successfully.", "success");
            if (currentScriptId === scriptId) {
                currentScriptId = null;
                scriptName = "";
            }
            await loadSavedScripts();
        } catch (err) {
            console.error("Error deleting script:", err);
            addNotification("Failed to delete script.", "error");
        }
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
            script.set(text);
            if (editor) {
                editor.dispatch({
                    changes: {from: 0, to: editor.state.doc.length, insert: text},
                });
            }
        };
        reader.readAsText(file);
    }
</script>

<!-- Hidden file input for uploading .py files -->
<input
        type="file"
        accept=".py"
        bind:this={fileInput}
        on:change={handleFileUpload}
        style="display: none;"
/>

<div class="container" in:fade>
    <!-- Row 1: Header -->
    <div class="header-row">
        <div class="header-left">
            <h2 class="title">Python Code Editor</h2>
        </div>
        <div class="header-right">
            {#if k8sLimits}
                <div class="limits-container">
                    <!-- Make the button fill its container's width -->
                    <button class="limits-toggle full-width" on:click={toggleLimits}>
                        <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                             xmlns="http://www.w3.org/2000/svg">
                            <path
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    stroke-width="2"
                                    d="M13 10V3L4 14h7v7l9-11h-7z"
                            ></path>
                        </svg>
                        Resource Limits
                        <svg class="icon arrow" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                             xmlns="http://www.w3.org/2000/svg">
                            <path
                                    stroke-linecap="round"
                                    stroke-linejoin="round"
                                    stroke-width="2"
                                    d={showLimits ? "M19 9l-7 7-7-7" : "M9 5l7 7-7 7"}
                            ></path>
                        </svg>
                    </button>
                    {#if showLimits}
                        <div class="limits-grid" transition:fly={{ y: -20, duration: 300 }}>
                            <div class="limit-item">
                                <div class="limit-icon">
                                    <svg
                                            class="w-6 h-6"
                                            fill="none"
                                            stroke="currentColor"
                                            viewBox="0 0 24 24"
                                            xmlns="http://www.w3.org/2000/svg"
                                    >
                                        <path
                                                stroke-linecap="round"
                                                stroke-linejoin="round"
                                                stroke-width="2"
                                                d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"
                                        ></path>
                                    </svg>
                                </div>
                                <div class="limit-details">
                                    <span class="limit-label">CPU Limit</span>
                                    <span class="limit-value">{k8sLimits.cpu_limit}</span>
                                </div>
                            </div>
                            <div class="limit-item">
                                <div class="limit-icon">
                                    <svg
                                            class="w-6 h-6"
                                            fill="none"
                                            stroke="currentColor"
                                            viewBox="0 0 24 24"
                                            xmlns="http://www.w3.org/2000/svg"
                                    >
                                        <path
                                                stroke-linecap="round"
                                                stroke-linejoin="round"
                                                stroke-width="2"
                                                d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                                        ></path>
                                    </svg>
                                </div>
                                <div class="limit-details">
                                    <span class="limit-label">Memory Limit</span>
                                    <span class="limit-value">{k8sLimits.memory_limit}</span>
                                </div>
                            </div>
                            <div class="limit-item">
                                <div class="limit-icon">
                                    <svg
                                            class="w-6 h-6"
                                            fill="none"
                                            stroke="currentColor"
                                            viewBox="0 0 24 24"
                                            xmlns="http://www.w3.org/2000/svg"
                                    >
                                        <path
                                                stroke-linecap="round"
                                                stroke-linejoin="round"
                                                stroke-width="2"
                                                d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                                        ></path>
                                    </svg>
                                </div>
                                <div class="limit-details">
                                    <span class="limit-label">Execution Timeout</span>
                                    <span class="limit-value">{k8sLimits.execution_timeout} seconds</span>
                                </div>
                            </div>
                        </div>
                    {/if}
                </div>
            {/if}
        </div>
    </div>

    <!-- Row 2: Main Content -->
    <div class="main-row">
        <div class="code-column">
            <!-- Removed fixed height so it expands as needed -->
            <div id="editor-container" class="editor-container"></div>
        </div>
        <div class="output-column">
            <!-- Also removed fixed height so it expands with content -->
            <div class="result-container">
                <h3 class="result-title">Execution Output</h3>
                <p class="result-description">
                    Here you'll see the output of your script, including any errors or results.
                </p>
                {#if executing}
                    <div class="result-content" in:fade>
                        <Spinner/>
                        <p class="executing-text">Executing script...</p>
                    </div>
                {:else if error}
                    <p class="error result-content" in:fly={{ y: 20, duration: 300 }}>
                        {error}
                    </p>
                {:else if result}
                    <div class="result-content" in:fly={{ y: 20, duration: 300 }}>
                        <p><strong>Status:</strong> {result.status}</p>
                        <p><strong>Execution ID:</strong> {result.execution_id}</p>
                        {#if result.output}
                            <p><strong>Output:</strong></p>
                            <pre class="output">{result.output}</pre>
                        {/if}
                        {#if result.errors}
                            <p><strong>Errors:</strong></p>
                            <pre class="error">{result.errors}</pre>
                        {/if}
                        {#if result.resource_usage}
                            <div class="resource-usage">
                                <h4>Resource Usage:</h4>
                                <p><strong>CPU Usage:</strong> {result.resource_usage.cpu_usage}</p>
                                <p><strong>Memory Usage:</strong> {result.resource_usage.memory_usage}</p>
                                <p>
                                    <strong>Execution Time:</strong>
                                    {result.resource_usage.execution_time.toFixed(2)} seconds
                                </p>
                            </div>
                        {/if}
                    </div>
                {:else}
                    <p class="result-content">
                        Run your script to see the output here.
                    </p>
                {/if}
            </div>
        </div>
    </div>

    <!-- Row 3: Controls -->
    <div class="controls-row">
        <div class="editor-controls">
            <div class="primary-controls">
                <div class="control-group">
                    <select bind:value={$pythonVersion} class="version-select">
                        {#each supportedPythonVersions as version}
                            <option value={version}>Python {version}</option>
                        {/each}
                    </select>
                    <button class="button primary" on:click={executeScript} disabled={executing}>
                        {executing ? "Executing..." : "Run Script"}
                    </button>
                    <button class="button secondary" on:click={() => (showOptions = !showOptions)}>
                        {showOptions ? "Hide Options" : "Show Options"}
                    </button>
                </div>
            </div>
            {#if showOptions}
                <div class="secondary-controls" transition:slide>
                    <div class="control-panel">
                        <div class="control-group">
                            <button class="button control" on:click={newScript}>
                                <svg class="icon" viewBox="0 0 24 24">
                                    <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
                                </svg>
                                New
                            </button>
                            <button class="button control" on:click={() => fileInput.click()}>
                                <svg class="icon" viewBox="0 0 24 24">
                                    <path d="M9 16h6v-6h4l-7-7-7 7h4v6zm-4 2h14v2H5v-2z"/>
                                </svg>
                                Upload
                            </button>
                            <button class="button control" on:click={exportScript}>
                                <svg class="icon" viewBox="0 0 24 24">
                                    <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>
                                </svg>
                                Export
                            </button>
                        </div>
                    </div>
                    {#if isAuthenticated}
                        <div class="control-panel">
                            <div class="save-control-group">
                                <input
                                        type="text"
                                        class="script-name-input"
                                        placeholder="Script Name"
                                        bind:value={scriptName}
                                />
                                <div class="save-buttons-group">
                                    <button class="button primary" on:click={saveScript}>
                                        Save Script
                                    </button>
                                    <button
                                            class="button icon-only"
                                            on:click={toggleSavedScripts}
                                            title={showSavedScripts ? "Hide Saved Scripts" : "Show Saved Scripts"}
                                    >
                                        <svg viewBox="0 0 24 24" class="icon toggle-icon">
                                            {#if showSavedScripts}
                                                <path
                                                        d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"
                                                        fill="#3b82f6"
                                                />
                                                <path d="M12 9l-3 3 3 3 3-3z" fill="#3b82f6"/>
                                            {:else}
                                                <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                                            {/if}
                                        </svg>
                                    </button>
                                </div>
                            </div>
                        </div>
                    {/if}
                </div>
            {/if}
            {#if showSavedScripts}
                <div class="saved-scripts-panel" transition:slide>
                    <h3>Your Saved Scripts</h3>
                    {#if savedScripts.length > 0}
                        <ul class="scripts-list">
                            {#each savedScripts as savedScript (savedScript.id)}
                                <li class="script-item">
                                    <button
                                            class="script-name"
                                            on:click={() => loadScript(savedScript)}
                                    >
                                        {savedScript.name}
                                    </button>
                                    <button
                                            class="delete-button"
                                            on:click|stopPropagation={() => deleteScript(savedScript.id)}
                                    >
                                        <svg viewBox="0 0 24 24" class="icon delete-icon">
                                            <polyline points="3 6 5 6 21 6"/>
                                            <path
                                                    d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"
                                            />
                                            <line x1="10" y1="11" x2="10" y2="17"/>
                                            <line x1="14" y1="11" x2="14" y2="17"/>
                                        </svg>
                                    </button>
                                </li>
                            {/each}
                        </ul>
                    {:else}
                        <p class="no-scripts-message">You have no saved scripts.</p>
                    {/if}
                </div>
            {/if}
        </div>
    </div>
</div>


<style>
    /* --- CodeMirror Global Styles --- */
    :global(.cm-editor) {
        height: 100%;
        font-family: "Fira Code", monospace;
        font-size: 14px;
    }

    :global(.cm-gutters) {
        border-right: 1px solid #e2e8f0;
        background-color: #f7fafc;
    }

    :global(.cm-lineNumbers) {
        padding: 0 3px 0 5px;
        min-width: 20px;
        text-align: right;
        color: #718096;
    }

    :global(.cm-scroller) {
        overflow-x: auto !important;
        overflow-y: auto !important;
        white-space: nowrap;
        height: 100%;
    }

    :global(.cm-content) {
        white-space: pre;
    }

    /* --- Container ---
       - No fixed height: grows as needed
       - Centered card with top/bottom margin and padding */
    .container {
        max-width: 1200px;
        margin: 2rem auto; /* top margin => space above header */
        padding: 2rem;
        background-color: #ffffff;
        border-radius: 0.5rem;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);

        display: flex;
        flex-direction: column;
        box-sizing: border-box;
    }

    /* --- Row 1: Header (70/30) --- */
    .header-row {
        display: flex;
        gap: 1rem;
        margin-bottom: 1.5rem;
    }

    .header-left {
        width: 70%;
    }

    .header-right {
        width: 30%;
    }

    .title {
        font-size: 1.5rem;
        color: #2d3748;
        margin: 0;
    }

    /* Resource Limits button & dropdown */
    .limits-container {
        position: relative;
        display: inline-block;
        vertical-align: top;
        width: 100%;
    }

    .limits-toggle {
        display: inline-flex;
        align-items: center;
        background-color: #edf2f7;
        border: none;
        border-radius: 0.375rem;
        padding: 0.5rem 1rem;
        font-size: 0.875rem;
        color: #4a5568;
        font-weight: 600;
        cursor: pointer;
        transition: background-color 0.2s ease;
    }

    .limits-toggle:hover {
        background-color: #e2e8f0;
    }

    .limits-toggle.full-width {
        width: 100%;
    }

    .icon {
        width: 1.25rem;
        height: 1.25rem;
        margin-right: 0.5rem;
        fill: none;
        stroke: currentColor;
        stroke-width: 2;
        stroke-linecap: round;
        stroke-linejoin: round;
    }

    .arrow {
        margin-left: auto;
        margin-right: 0.25rem;
    }

    .limits-grid {
        position: absolute;
        top: 100%;
        left: 0;
        margin-top: 0.5rem;
        z-index: 10;
        width: 100%;
        min-width: 200px;
        background-color: #ffffff;
        border-radius: 0.375rem;
        padding: 1rem 1rem 0.5rem 1rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }

    .limit-item {
        display: flex;
        align-items: center;
        margin-bottom: 0.75rem;
    }

    .limit-icon {
        background-color: #ebf8ff;
        border-radius: 50%;
        padding: 0.5rem;
        margin-right: 0.75rem;
    }

    .limit-details {
        display: flex;
        flex-direction: column;
    }

    .limit-label {
        font-size: 0.75rem;
        color: #718096;
    }

    .limit-value {
        font-size: 0.875rem;
        color: #2d3748;
        font-weight: 600;
    }

    /* --- Row 2: Main Content (70/30) --- */
    .main-row {
        display: flex;
        gap: 1.5rem;
        margin-bottom: 1.5rem;
    }

    .code-column {
        width: 70%;
        overflow: hidden;
    }

    .output-column {
        width: 30%;
    }

    /* Editor container: fixed height => scroll instead of pushing content */
    .editor-container {
        border: 1px solid #e2e8f0;
        border-radius: 0.375rem;
        width: 100%;
        height: 600px; /* Fix a height so it won't overlap controls */
        overflow: auto;
    }

    .result-container {
        background-color: #f7fafc;
        border-radius: 0.375rem;
        padding: 1rem;
        overflow-y: auto;
    }

    /* --- Row 3: Controls Row ---
       - Normal block flow => “Show Options” expands downward */
    .controls-row {
        width: 100%;
        margin-top: 1rem;
        display: block;
        clear: both;
    }

    .editor-controls {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .primary-controls {
        display: flex;
        align-items: center;
    }

    .control-group {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
    }

    .secondary-controls {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 16px;
        background-color: #f8fafc;
        border-radius: 8px;
        border: 1px solid #e2e8f0;
    }

    .control-panel {
        padding-bottom: 12px;
        border-bottom: 1px solid #e2e8f0;
        width: 100%;
    }

    .control-panel:last-child {
        border-bottom: none;
        padding-bottom: 0;
    }

    /* Buttons & Inputs */
    .version-select {
        height: 38px;
        padding: 0 12px;
        border-radius: 6px;
        border: 1px solid #cbd5e1;
        background-color: #f7fafc;
        font-size: 14px;
        color: #334155;
        min-width: 120px;
    }

    .button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 0.5rem 1rem;
        font-size: 0.875rem;
        font-weight: 500;
        border-radius: 0.375rem;
        cursor: pointer;
        transition: all 0.2s ease;
        height: 38px;
    }

    .button.primary {
        background-color: #4299e1;
        color: #ffffff;
        border: none;
    }

    .button.primary:hover:not(:disabled) {
        background-color: #3182ce;
    }

    .button.secondary {
        background-color: #edf2f7;
        color: #4a5568;
        border: 1px solid #e2e8f0;
    }

    .button.secondary:hover {
        background-color: #e2e8f0;
    }

    .button.control {
        background-color: white;
        color: #475569;
        border: 1px solid #cbd5e1;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }

    .button.control .icon {
        width: 18px;
        height: 18px;
        fill: currentColor;
        stroke: none;
        margin-right: 0;
    }

    .button.control:hover {
        background-color: #f1f5f9;
    }

    .button.icon-only {
        width: 38px;
        padding: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        background-color: white;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
    }

    .button.icon-only:hover {
        background-color: #f1f5f9;
    }

    .button.icon-only .icon {
        margin-right: 0;
    }

    .button:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }

    /* “Save” row inputs */
    .save-control-group {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
    }

    .script-name-input {
        flex: 1;
        min-width: 100px;
        height: 38px;
        padding: 0 12px;
        border-radius: 6px;
        border: 1px solid #cbd5e1;
        font-size: 14px;
    }

    /* We push the group of Save + icon button to the right */
    .save-buttons-group {
        margin-left: auto;
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
    }

    /* Saved scripts panel */
    .saved-scripts-panel {
        background-color: white;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 16px;
        margin-top: 8px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }

    .saved-scripts-panel h3 {
        margin-top: 0;
        font-size: 16px;
        color: #334155;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid #e2e8f0;
    }

    .scripts-list {
        list-style-type: none;
        padding: 0;
        margin: 0;
    }

    .script-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 0;
        border-bottom: 1px solid #f1f5f9;
    }

    .script-item:last-child {
        border-bottom: none;
    }

    .script-name {
        background: none;
        border: none;
        color: #3b82f6;
        cursor: pointer;
        text-align: left;
        font-size: 14px;
        padding: 0;
    }

    .script-name:hover {
        text-decoration: underline;
    }

    .delete-button {
        background: none;
        border: none;
        padding: 4px;
        color: #ef4444;
        cursor: pointer;
        border-radius: 4px;
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .delete-button:hover {
        background-color: #fee2e2;
    }

    .delete-button .icon {
        margin: 0;
        display: block;
    }

    /* Execution Output & Error Boxes */
    .result-title {
        font-size: 1.25rem;
        color: #2d3748;
        margin-bottom: 0.5rem;
        font-weight: 600;
    }

    .result-description {
        font-size: 0.875rem;
        color: #718096;
        margin-bottom: 1rem;
    }

    .result-content {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 0.375rem;
        padding: 1rem;
        overflow-y: auto;
        max-height: 500px;
    }

    .executing-text {
        text-align: center;
        color: #4299e1;
        font-weight: bold;
    }

    pre {
        white-space: pre-wrap;
        word-wrap: break-word;
        background-color: #f0f0f0;
        padding: 1rem;
        border-radius: 0.375rem;
        font-size: 0.875rem;
        line-height: 1.5;
    }

    .output {
        background-color: #e6fffa;
        border: 1px solid #b2f5ea;
    }

    .error {
        background-color: #fff5f5;
        border: 1px solid #fed7d7;
        color: #c53030;
    }

    .resource-usage {
        margin-top: 1rem;
        padding: 1rem;
        background-color: #ebf8ff;
        border: 1px solid #bee3f8;
        border-radius: 0.375rem;
    }

    .resource-usage h4 {
        margin-bottom: 0.5rem;
        font-weight: 600;
        color: #2c5282;
    }

    /* --- Responsive (max-width: 768px) --- */
    @media (max-width: 768px) {
        .container {
            padding: 1rem;
            height: auto; /* no forced height on small screens */
        }

        .header-row {
            flex-direction: column;
        }

        .header-left,
        .header-right {
            width: 100%;
        }

        .main-row {
            flex-direction: column;
        }

        .code-column,
        .output-column {
            width: 100%;
            margin-bottom: 1.5rem;
        }

        .editor-container {
            height: 400px; /* shorter on mobile if desired */
        }

        .control-group {
            flex-direction: column;
            align-items: stretch;
            width: 100%;
        }

        .script-name-input {
            max-width: none;
        }

        .button,
        .version-select {
            width: 100%;
        }

        .editor-controls,
        .primary-controls,
        .secondary-controls {
            flex-direction: column;
            width: 100%;
        }

        .secondary-controls {
            gap: 0.75rem;
            justify-content: flex-start;
        }

        .version-select,
        .button,
        .script-name-input {
            width: 100%;
        }

        .limits-grid {
            left: 0;
            right: auto;
            width: calc(100vw - 2rem);
            max-width: none;
        }
    }
</style>



