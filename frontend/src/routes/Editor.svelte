<script>
    import {onMount} from "svelte";
    import {fade, fly} from "svelte/transition";
    import {get, writable} from "svelte/store";
    import axios from "axios";
    import {authToken} from "../stores/auth.js";
    import {addNotification} from "../stores/notifications.js";
    import Spinner from "../components/Spinner.svelte";
    import {navigate} from "svelte-routing";

    import {EditorState} from "@codemirror/state";
    import {EditorView, keymap, lineNumbers} from "@codemirror/view";
    import {defaultKeymap} from "@codemirror/commands";
    import {python} from "@codemirror/lang-python";
    import {oneDark} from "@codemirror/theme-one-dark";

    // Custom persistent store
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

    onMount(async () => {
        const authTokenValue = get(authToken);
        if (!authTokenValue) {
            addNotification("Please log in to access the editor.", "error");
            navigate("/login");
            return;
        }

        try {
            // Verify the token with the backend
            await axios.get("http://localhost:8000/api/v1/verify-token", {
                headers: {Authorization: `Bearer ${authTokenValue}`}
            });
        } catch (err) {
            localStorage.removeItem("authToken");
            authToken.set(null);
            addNotification("Your session has expired. Please log in again.", "error");
            navigate("/login");
            return;
        }

        try {
            const limitsResponse = await axios.get(
                "http://localhost:8000/api/v1/k8s-limits",
                {
                    headers: {Authorization: `Bearer ${authTokenValue}`}
                }
            );
            k8sLimits = limitsResponse.data;
        } catch (err) {
            console.error("Error fetching K8s limits:", err);
            addNotification("Failed to fetch resource limits.", "error");
        }

        // Create the initial editor state
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

        // Create the editor view and attach it to a DOM element
        editor = new EditorView({
            state: startState,
            parent: document.getElementById("editor-container"),
        });
    });

    async function executeScript() {
        executing = true;
        error = "";
        result = null;

        const scriptValue = get(script);
        const authTokenValue = get(authToken);

        try {
            const executeResponse = await axios.post(
                "http://localhost:8000/api/v1/execute",
                {script: scriptValue},
                {
                    headers: {Authorization: `Bearer ${authTokenValue}`}
                }
            );

            const executionId = executeResponse.data.execution_id;

            // Poll for results
            while (true) {
                const resultResponse = await axios.get(
                    `http://localhost:8000/api/v1/result/${executionId}`,
                    {
                        headers: {Authorization: `Bearer ${authTokenValue}`}
                    }
                );

                if (
                    resultResponse.data.status === "completed" ||
                    resultResponse.data.status === "failed"
                ) {
                    console.log("Full response:", resultResponse.data);
                    result = resultResponse.data;
                    break;
                }

                await new Promise(resolve => setTimeout(resolve, 1000)); // Wait 1 second before polling again
            }
        } catch (err) {
            if (err.response && err.response.status === 401) {
                // Handle 401 Unauthorized error
                addNotification("Your session has expired. Please log in again.", "error");
                localStorage.removeItem("authToken");
                authToken.set(null);
                navigate("/login");
            } else {
                error = err.response?.data?.detail || "An error occurred while executing the script.";
                console.error("Error executing script:", err);
            }
        } finally {
            executing = false;
        }
    }
</script>

<div class="container" in:fade>
    <h2 class="title">Python Code Editor</h2>

    {#if k8sLimits}
        <div class="limits-container mb-6" in:fly={{ y: 20, duration: 300 }}>
            <h3 class="limits-title">
                <svg class="inline-block w-6 h-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                     xmlns="http://www.w3.org/2000/svg">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                          d="M13 10V3L4 14h7v7l9-11h-7z"></path>
                </svg>
                Execution Resource Limits
            </h3>
            <div class="limits-grid">
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
                                  d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"></path>
                        </svg>
                    </div>
                    <div class="limit-details">
                        <span class="limit-label">CPU Request</span>
                        <span class="limit-value">{k8sLimits.cpu_request}</span>
                    </div>
                </div>
                <div class="limit-item">
                    <div class="limit-icon">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"
                             xmlns="http://www.w3.org/2000/svg">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                  d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"></path>
                        </svg>
                    </div>
                    <div class="limit-details">
                        <span class="limit-label">Memory Request</span>
                        <span class="limit-value">{k8sLimits.memory_request}</span>
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
        </div>
    {/if}


    <div class="flex flex-col lg:flex-row">
        <div class="editor-section w-full lg:w-2/3 lg:pr-4">
            <div id="editor-container" class="editor-container"></div>
            <button class="button w-full mt-4" on:click={executeScript} disabled={executing}>
                {#if executing}
                    Executing...
                {:else}
                    Run Script
                {/if}
            </button>
        </div>
        <div class="result-section w-full lg:w-1/3 mt-4 lg:mt-0">
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
                    </div>
                {:else}
                    <p class="result-content">Run your script to see the output here.</p>
                {/if}
            </div>
        </div>
    </div>
</div>

<style>
    .limits-container {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }

    .limits-title {
        font-size: 1.25rem;
        color: #2d3748;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        font-weight: 600;
    }

    .limits-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 1rem;
    }

    .limit-item {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        display: flex;
        align-items: center;
        transition: all 0.3s ease;
    }

    .limit-item:hover {
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        transform: translateY(-2px);
    }

    .limit-icon {
        background-color: #ebf8ff;
        border-radius: 50%;
        padding: 0.5rem;
        margin-right: 1rem;
    }

    .limit-icon svg {
        color: #3182ce;
    }

    .limit-details {
        display: flex;
        flex-direction: column;
    }

    .limit-label {
        font-size: 0.875rem;
        color: #4a5568;
        margin-bottom: 0.25rem;
    }

    .limit-value {
        font-size: 1rem;
        color: #2d3748;
        font-weight: 600;
    }

    .container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 2rem 1rem;
        background-color: #ffffff;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }

    .title {
        font-size: 2rem;
        color: #333;
        margin-bottom: 1.5rem;
        text-align: center;
    }

    .editor-container {
        height: 600px;
        border: 1px solid #dbdbdb;
        border-radius: 4px;
        overflow: hidden;
    }

    .button {
        background-color: #3273dc;
        color: #ffffff;
        border: none;
        padding: 0.5rem 1rem;
        font-size: 1rem;
        border-radius: 4px;
        cursor: pointer;
        transition: background-color 0.3s ease;
    }

    .button:hover:not(:disabled) {
        background-color: #2366d1;
    }

    .button:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }

    .result-container {
        padding: 1rem;
        background-color: #f5f5f5;
        border-radius: 4px;
        height: 100%;
        overflow-y: auto;
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
        font-size: 0.9rem;
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

    .result-container {
        background-color: #f8fafc;
        border: 2px solid #e2e8f0;
        border-radius: 8px;
        padding: 1rem;
        height: 100%;
        display: flex;
        flex-direction: column;
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
        flex-grow: 1;
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 1rem;
        overflow-y: auto;
    }

    .executing-text {
        text-align: center;
        color: #3182ce;
        font-weight: bold;
    }

    .error {
        color: #e53e3e;
    }

    .output {
        background-color: #edf2f7;
        border: 1px solid #e2e8f0;
        border-radius: 4px;
        padding: 0.5rem;
        font-family: 'Fira Code', monospace;
        font-size: 0.875rem;
    }


    :global(.cm-editor) {
        height: 100%;
        font-family: 'Fira Code', monospace;
        font-size: 14px;
    }

    :global(.cm-gutters) {
        border-right: 1px solid #ddd;
        background-color: #f7f7f7;
        white-space: nowrap;
    }

    :global(.cm-lineNumbers) {
        padding: 0 3px 0 5px;
        min-width: 20px;
        text-align: right;
        color: #999;
    }
</style>