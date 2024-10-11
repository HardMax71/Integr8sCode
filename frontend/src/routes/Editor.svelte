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
            error = err.response?.data?.detail || "An error occurred while executing the script.";
            console.error("Error executing script:", err);
        } finally {
            executing = false;
        }
    }
</script>

<div class="container" in:fade>
    <h2 class="title">Python Code Editor</h2>
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
            {#if executing}
                <div class="result-container" in:fade>
                    <Spinner/>
                    <p class="executing-text">Executing script...</p>
                </div>
            {:else if error}
                <p class="error" in:fly={{ y: 20, duration: 300 }}>{error}</p>
            {:else if result}
                <div class="result-container" in:fly={{ y: 20, duration: 300 }}>
                    <h3 class="subtitle">Execution Result</h3>
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
            {/if}
        </div>
    </div>
</div>

<style>
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

    .subtitle {
        font-size: 1.5rem;
        color: #333;
        margin-bottom: 1rem;
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