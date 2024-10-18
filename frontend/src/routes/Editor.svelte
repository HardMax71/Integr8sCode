<script>
    import {onMount} from "svelte";
    import {fade, fly} from "svelte/transition";
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

    let isAuthenticated = false;
    let savedScripts = [];
    let showSavedScripts = false;
    let scriptName = "";
    let currentScriptId = null;

    // Watch authToken to determine authentication status
    authToken.subscribe(token => {
        isAuthenticated = !!token;
    });

    onMount(async () => {
        try {
            const limitsResponse = await axios.get(
                `${backendUrl}/api/v1/k8s-limits`
            );
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
        const blob = new Blob([get(script)], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const filename = scriptName ? `${scriptName}` : 'script.py'; // Use scriptName if available
        const a = document.createElement('a');
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
                // Update existing script
                await axios.put(
                    `${backendUrl}/api/v1/scripts/${currentScriptId}`,
                    { name: scriptName, script: scriptValue },
                    {
                        headers: { Authorization: `Bearer ${authTokenValue}` },
                    }
                );
                addNotification("Script updated successfully.", "success");
            } else {
                // Create new script
                const response = await axios.post(
                    `${backendUrl}/api/v1/scripts`,
                    { name: scriptName, script: scriptValue },
                    {
                        headers: { Authorization: `Bearer ${authTokenValue}` },
                    }
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


    async function loadSavedScripts() {
        const authTokenValue = get(authToken);

        try {
            const response = await axios.get(
                `${backendUrl}/api/v1/scripts`,
                {
                    headers: { Authorization: `Bearer ${authTokenValue}` },
                }
            );
            savedScripts = response.data;
        } catch (err) {
            console.error("Error loading saved scripts:", err);
            addNotification("Failed to load saved scripts.", "error");
        }
    }

    function toggleSavedScripts() {
        showSavedScripts = !showSavedScripts;
    }

    function loadScript(scriptData) {
        script.set(scriptData.script);
        scriptName = scriptData.name;
        currentScriptId = scriptData.id; // Set the current script ID
        // Update the editor's content
        editor.dispatch({
            changes: {
                from: 0,
                to: editor.state.doc.length,
                insert: scriptData.script,
            }
        });
        addNotification(`Loaded script: ${scriptData.name}`, "info");
        showSavedScripts = false;
    }

    function newScript() {
        script.set("");
        scriptName = "";
        currentScriptId = null;
        // Clear the editor content
        editor.dispatch({
            changes: {
                from: 0,
                to: editor.state.doc.length,
                insert: "",
            }
        });
    }

    async function deleteScript(scriptId) {
        const confirmDelete = confirm("Are you sure you want to delete this script?");
        if (!confirmDelete) {
            return;
        }

        const authTokenValue = get(authToken);

        try {
            await axios.delete(
                `${backendUrl}/api/v1/scripts/${scriptId}`,
                {
                    headers: { Authorization: `Bearer ${authTokenValue}` },
                }
            );
            addNotification("Script deleted successfully.", "success");
            // If the deleted script is the one currently loaded, reset currentScriptId and scriptName
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
</script>

<div class="container" in:fade>
    <div class="header-row">
        <h2 class="title">Python Code Editor</h2>
        {#if k8sLimits}
            <div class="limits-container">
                <button class="limits-toggle" on:click={toggleLimits}>
                    <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                         xmlns="http://www.w3.org/2000/svg">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                              d="M13 10V3L4 14h7v7l9-11h-7z"></path>
                    </svg>
                    Resource Limits
                    <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                         xmlns="http://www.w3.org/2000/svg">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                              d={showLimits ? "M19 9l-7 7-7-7" : "M9 5l7 7-7 7"}></path>
                    </svg>
                </button>
                {#if showLimits}
                    <div class="limits-grid" transition:fly={{ y: -20, duration: 300 }}>
                        <div class="limit-item">
                            <div class="limit-icon">
                                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                                     xmlns="http://www.w3.org/2000/svg">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                          d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"></path>
                                </svg>
                            </div>
                            <div class="limit-details">
                                <span class="limit-label">CPU Limit</span>
                                <span class="limit-value">{k8sLimits.cpu_limit}</span>
                            </div>
                        </div>
                        <div class="limit-item">
                            <div class="limit-icon">
                                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                                     xmlns="http://www.w3.org/2000/svg">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                          d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path>
                                </svg>
                            </div>
                            <div class="limit-details">
                                <span class="limit-label">Memory Limit</span>
                                <span class="limit-value">{k8sLimits.memory_limit}</span>
                            </div>
                        </div>
                        <div class="limit-item">
                            <div class="limit-icon">
                                <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                                     xmlns="http://www.w3.org/2000/svg">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                          d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
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

    <div class="editor-result-container">
        <div class="editor-section">
            <div id="editor-container" class="editor-container"></div>
            <div class="editor-controls">
                <select bind:value={$pythonVersion} class="version-select">
                    {#each supportedPythonVersions as version}
                        <option value={version}>Python {version}</option>
                    {/each}
                </select>
                <button class="button" on:click={executeScript} disabled={executing}>
                    {executing ? 'Executing...' : 'Run Script'}
                </button>
                <button class="icon-button" on:click={exportScript} title="Export Script">
                    Export
                </button>
                {#if isAuthenticated}
                    <input
                            type="text"
                            class="script-name-input"
                            placeholder="Script Name"
                            bind:value={scriptName}
                    />
                    <button class="button" on:click={saveScript}>
                        Save Script
                    </button>
                    <button class="button" on:click={toggleSavedScripts}>
                        {showSavedScripts ? 'Hide' : 'Show'} Saved Scripts
                    </button>
                    <button class="button" on:click={newScript}>
                        New Script
                    </button>
                {/if}
            </div>
            {#if showSavedScripts}
                <div class="saved-scripts" transition:fly={{ y: -20, duration: 300 }}>
                    <h3>Your Saved Scripts</h3>
                    {#if savedScripts.length > 0}
                        <ul>
                            {#each savedScripts as savedScript}
                                <li>
                                    <span on:click={() => loadScript(savedScript)} class="script-link">
                                        {savedScript.name}
                                    </span>
                                    <button class="delete-button" on:click|stopPropagation={() => deleteScript(savedScript.id)}>
                                        Delete
                                    </button>
                                </li>
                            {/each}
                        </ul>
                    {:else}
                        <p>You have no saved scripts.</p>
                    {/if}
                </div>
            {/if}
        </div>
        <div class="result-section">
            <div class="result-container">
                <h3 class="result-title">Execution Output</h3>
                <p class="result-description">Here you'll see the output of your script, including any errors or
                    results.</p>
                {#if executing}
                    <div class="result-content" in:fade>
                        <Spinner/>
                        <p class="executing-text">Executing script...</p>
                    </div>
                {:else if error}
                    <p class="error result-content" in:fly={{ y: 20, duration: 300 }}>{error}</p>
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
                                <p><strong>Execution Time:</strong> {result.resource_usage.execution_time.toFixed(2)}
                                    seconds</p>
                            </div>
                        {/if}
                    </div>
                {:else}
                    <p class="result-content">Run your script to see the output here.</p>
                {/if}
            </div>
        </div>
    </div>
</div>

<style>
    .container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 1rem;
        background-color: #ffffff;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }

    .header-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-top: 1.5rem;
        margin-bottom: 1rem;
    }

    .title {
        font-size: 1.5rem;
        color: #333;
        margin: 0;
    }

    .limits-container {
        flex-shrink: 0;
        position: relative;
    }

    .limits-toggle {
        display: flex;
        align-items: center;
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        font-size: 0.875rem;
        color: #2d3748;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
    }

    .limits-toggle:hover {
        background-color: #edf2f7;
    }

    .icon {
        width: 1.25rem;
        height: 1.25rem;
        margin-right: 0.5rem;
    }

    .limits-grid {
        position: absolute;
        top: 100%;
        right: 0;
        margin-top: 0.5rem;
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        z-index: 10;
    }

    .limit-item {
        display: flex;
        align-items: center;
        margin-bottom: 0.5rem;
    }

    .limit-icon {
        background-color: #ebf8ff;
        border-radius: 50%;
        padding: 0.25rem;
        margin-right: 0.5rem;
    }

    .limit-icon svg {
        width: 1rem;
        height: 1rem;
        color: #3182ce;
    }

    .limit-details {
        display: flex;
        flex-direction: column;
    }

    .limit-label {
        font-size: 0.75rem;
        color: #4a5568;
    }

    .limit-value {
        font-size: 0.875rem;
        color: #2d3748;
        font-weight: 600;
    }

    .editor-result-container {
        display: flex;
        gap: 1rem;
    }

    .editor-section {
        flex: 2;
        display: flex;
        flex-direction: column;
    }

    .editor-container {
        height: 500px;
        border: 1px solid #e2e8f0;
        border-radius: 4px;
        overflow: hidden;
    }

    .editor-controls {
        display: flex;
        gap: 0.5rem;
        margin-top: 1rem;
    }

    .version-select {
        padding: 0.5rem;
        border-radius: 4px;
        border: 1px solid #e2e8f0;
        background-color: #ffffff;
        font-size: 0.875rem;
    }

    .button {
        background-color: #3273dc;
        color: #ffffff;
        border: none;
        padding: 0.5rem 1rem;
        font-size: 0.875rem;
        border-radius: 4px;
        cursor: pointer;
        transition: background-color 0.3s ease;
        flex-grow: 1;
    }

    .button:hover:not(:disabled) {
        background-color: #2366d1;
    }

    .button:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }

    .icon-button {
        background-color: #4a5568;
        color: #ffffff;
        border: none;
        padding: 0.5rem;
        font-size: 0.875rem;
        border-radius: 4px;
        cursor: pointer;
        transition: background-color 0.3s ease;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .icon-button:hover {
        background-color: #2d3748;
    }

    .result-section {
        flex: 1;
    }

    .result-container {
        background-color: #f7fafc;
        border-radius: 4px;
        padding: 1rem;
        height: 100%;
        overflow-y: auto;
    }

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
        border-radius: 4px;
        padding: 1rem;
        overflow-y: auto;
        max-height: 500px;
    }

    .executing-text {
        text-align: center;
        color: #3273dc;
        font-weight: bold;
    }

    pre {
        white-space: pre-wrap;
        word-wrap: break-word;
        background-color: #f0f0f0;
        padding: 1rem;
        border-radius: 4px;
        font-size: 0.875rem;
        line-height: 1.5;
    }

    .output {
        background-color: #e6f3ff;
        border: 1px solid #b3d9ff;
    }

    .error {
        background-color: #ffe6e6;
        border: 1px solid #ffb3b3;
        color: #cc0000;
    }

    .resource-usage {
        margin-top: 1rem;
        padding: 1rem;
        background-color: #f0f8ff;
        border: 1px solid #b0d4ff;
        border-radius: 4px;
    }

    .resource-usage h4 {
        margin-bottom: 0.5rem;
        font-weight: 600;
        color: #2c5282;
    }

    :global(.cm-editor) {
        height: 100%;
        font-family: 'Fira Code', monospace;
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

    .script-name-input {
        padding: 0.5rem;
        border-radius: 4px;
        border: 1px solid #e2e8f0;
        font-size: 0.875rem;
        flex-grow: 1;
        margin-right: 0.5rem;
    }

    .saved-scripts {
        margin-top: 1rem;
        background-color: #f7fafc;
        border: 1px solid #e2e8f0;
        border-radius: 4px;
        padding: 1rem;
    }

    .saved-scripts h3 {
        margin-top: 0;
        font-size: 1rem;
        color: #2d3748;
    }

    .saved-scripts ul {
        list-style-type: none;
        padding-left: 0;
    }

    .saved-scripts li {
        margin-bottom: 0.5rem;
    }

    .script-link {
        color: #3273dc;
        cursor: pointer;
        text-decoration: underline;
    }

    .script-link:hover {
        color: #2366d1;
    }

    .delete-button {
        background-color: transparent;
        border: none;
        color: #e53e3e;
        cursor: pointer;
        font-size: 0.875rem;
        margin-left: 0.5rem;
    }

    .delete-button:hover {
        color: #c53030;
    }

    @media (max-width: 768px) {
        .header-row {
            flex-direction: row;
            flex-wrap: nowrap;
            align-items: center;
            justify-content: space-between;
        }

        .title {
            font-size: 1rem;
            margin-bottom: 0;
            margin-right: 0.5rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .limits-container {
            margin-top: 0;
            margin-left: 0;
        }

        .limits-toggle {
            font-size: 0.75rem;
            padding: 0.25rem 0.5rem;
            white-space: nowrap;
        }

        .icon {
            width: 0.875rem;
            height: 0.875rem;
            margin-right: 0.25rem;
        }

        .limits-grid {
            right: 0;
            left: auto;
            width: 100%;
            max-width: 300px;
        }

        .editor-result-container {
            flex-direction: column;
        }

        .editor-section, .result-section {
            width: 100%;
        }

        .editor-container {
            height: 400px;
        }

        .button, .icon-button {
            font-size: 0.75rem;
            padding: 0.25rem 0.5rem;
        }

        .version-select {
            font-size: 0.75rem;
            padding: 0.25rem;
        }
    }
</style>