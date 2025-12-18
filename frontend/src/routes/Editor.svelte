<script>
    import {onDestroy, onMount} from "svelte";
    import {fade, fly, slide} from "svelte/transition";
    import {get, writable} from "svelte/store";
        import {isAuthenticated, logout as authLogout, verifyAuth, csrfToken} from "../stores/auth.js";
    import {api} from "../lib/api.js";
    import {addToast} from "../stores/toastStore.js";
    import Spinner from "../components/Spinner.svelte";
    import {navigate} from "svelte-routing";
    import {Compartment, EditorState, StateEffect} from "@codemirror/state";
    import {EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers} from "@codemirror/view";
    import {defaultKeymap, history, historyKeymap, indentWithTab} from "@codemirror/commands";
    import {python} from "@codemirror/lang-python";
    import {oneDark} from "@codemirror/theme-one-dark";
    import {githubLight} from "@uiw/codemirror-theme-github";
    import {bracketMatching} from "@codemirror/language";
    import {autocompletion, completionKeymap} from "@codemirror/autocomplete";
    import {theme as appTheme} from "../stores/theme.js";
    import AnsiToHtml from 'ansi-to-html';
    import DOMPurify from 'dompurify';
    import { updateMetaTags, pageMeta } from '../utils/meta.js';
    import { getCachedSettings, settingsCache } from '../lib/settings-cache.js';
    import { loadUserSettings, saveEditorSettings } from '../lib/user-settings.js';

    let themeCompartment = new Compartment();
    let fontSizeCompartment = new Compartment();
    let tabSizeCompartment = new Compartment();
    let lineNumbersCompartment = new Compartment();
    let lineWrappingCompartment = new Compartment();
    
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

    function sanitizeOutput(html) {
        return DOMPurify.sanitize(html, {
            ALLOWED_TAGS: ['span', 'br', 'div'],
            ALLOWED_ATTR: ['class', 'style']
        });
    }

    function createPersistentStore(key, startValue) {
        if (typeof localStorage === 'undefined') {
            const store = writable(startValue);
            return {subscribe: store.subscribe, set: store.set};
        }
        const storedValue = localStorage.getItem(key);
        let parsedValue = startValue;
        
        if (storedValue) {
            try {
                parsedValue = JSON.parse(storedValue);
            } catch (e) {
                console.warn(`Failed to parse localStorage value for ${key}, using default:`, e);
                localStorage.removeItem(key); // Clear corrupted value
            }
        }
        
        const store = writable(parsedValue);
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
    let exampleScripts = {};

    // Updated state for language and version selection
    let selectedLang = writable("python");
    let selectedVersion = writable("3.11");
    let supportedRuntimes = {};
    let showLangOptions = false;
    let hoveredLang = null;

    let showLimits = false;
    let showOptions = false;
    let showSavedScripts = false;

    let authenticated = false;
    let savedScripts = [];
    let scriptName = createPersistentStore("scriptName", "");
    let currentScriptId = createPersistentStore("currentScriptId", null);

    let fileInput;
    let apiError = null;
    let unsubscribeAuth;
    let unsubscribeTheme;
    let unsubscribeSettings;

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
    const exportIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>`;
    const saveIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"></path></svg>`;
    const listIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16"></path></svg>`;
    const trashIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>`;
    const idIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>`;
    const copyIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"></path></svg>`;
    const exampleIcon = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path></svg>`;

    $: {
        if (typeof window !== 'undefined') { // Ensure this runs only in the browser
            const currentId = get(currentScriptId);
            const currentName = get(scriptName);

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
    }

    onMount(async () => {
        // Set meta tags
        updateMetaTags(pageMeta.editor.title, pageMeta.editor.description);
        
        // Verify authentication status on startup
        await verifyAuth();
        
        // Load user settings if authenticated
        if (authenticated) {
            const userSettings = await loadUserSettings();
            if (userSettings && userSettings.editor) {
                editorSettings = { ...editorSettings, ...userSettings.editor };
                // Migrate one-dark to auto for better theme following
                if (editorSettings.theme === 'one-dark') {
                    console.log('Migrating one-dark theme to auto');
                    editorSettings.theme = 'auto';
                }
                // If user has 'github' theme saved but app is in dark mode, switch to auto
                const currentAppTheme = get(appTheme);
                if (editorSettings.theme === 'github' && currentAppTheme === 'dark') {
                    console.log('User has light theme saved but app is dark - switching to auto');
                    editorSettings.theme = 'auto';
                }
            }
        }
        
        // Subscribe to settings cache updates
        unsubscribeSettings = settingsCache.subscribe(cached => {
            if (cached && cached.editor) {
                editorSettings = { ...editorSettings, ...cached.editor };
                // Migrate one-dark to auto for better theme following
                if (editorSettings.theme === 'one-dark') {
                    console.log('Migrating cached one-dark theme to auto');
                    editorSettings.theme = 'auto';
                }
                // If user has 'github' theme saved but app is in dark mode, switch to auto
                const currentAppTheme = get(appTheme);
                if (editorSettings.theme === 'github' && currentAppTheme === 'dark') {
                    console.log('Cached settings have light theme but app is dark - switching to auto');
                    editorSettings.theme = 'auto';
                }
                applyEditorSettings();
            }
        });
        
        unsubscribeAuth = isAuthenticated.subscribe(async authStatus => {
            const wasAuthenticated = authenticated;
            authenticated = authStatus;
            if (!wasAuthenticated && authenticated && editorView) {
                loadSavedScripts();
                // Load user settings when authenticated
                const userSettings = await loadUserSettings();
                if (userSettings && userSettings.editor) {
                    editorSettings = { ...editorSettings, ...userSettings.editor };
                    // Migrate one-dark to auto for better theme following
                    if (editorSettings.theme === 'one-dark') {
                        console.log('Migrating auth-loaded one-dark theme to auto');
                        editorSettings.theme = 'auto';
                    }
                    // If user has 'github' theme saved but app is in dark mode, switch to auto
                    const currentAppTheme = get(appTheme);
                    if (editorSettings.theme === 'github' && currentAppTheme === 'dark') {
                        console.log('Auth loaded settings have light theme but app is dark - switching to auto');
                        editorSettings.theme = 'auto';
                    }
                    applyEditorSettings();
                }
            } else if (wasAuthenticated && !authenticated) {
                savedScripts = [];
                showSavedScripts = false;
                currentScriptId.set(null);
                scriptName.set("");
            }
        });

        try {
            k8sLimits = await api.get(`/api/v1/k8s-limits`);
            supportedRuntimes = k8sLimits?.supported_runtimes || {"python": ["3.9", "3.10", "3.11"]};

            const currentLang = get(selectedLang);
            const currentVersion = get(selectedVersion);
            // Validate current selection
            if (!supportedRuntimes[currentLang] || !supportedRuntimes[currentLang].includes(currentVersion)) {
                // If invalid, reset to the first available option
                const firstLang = Object.keys(supportedRuntimes)[0];
                if (firstLang) {
                    const firstVersion = supportedRuntimes[firstLang][0];
                    selectedLang.set(firstLang);
                    if (firstVersion) {
                        selectedVersion.set(firstVersion);
                    }
                }
            }
        } catch (err) {
            apiError = "Failed to fetch resource limits.";
            addToast(apiError, "error");
            console.error("Error fetching K8s limits:", err);
            supportedRuntimes = {"python": ["3.9", "3.10", "3.11"]};
        }

        try {
            const examplesResponse = await api.get('/api/v1/example-scripts');
            exampleScripts = examplesResponse.scripts || {};
        } catch (err) {
            console.error("Error fetching example scripts:", err);
            addToast("Could not load example scripts.", "warning");
        }

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
            python(),
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
    
    function initializeEditor(currentTheme) {
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
        apiError = null;
        result = null;
        const scriptValue = get(script);
        const langValue = get(selectedLang);
        const versionValue = get(selectedVersion);
        let executionId = null;

        try {
            const executeResponse = await fetchWithRetry(`/api/v1/execute`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    script: scriptValue,
                    lang: langValue,
                    lang_version: versionValue
                })
            }, {
                numOfAttempts: 3,
                maxDelay: 5000
            });
            const executeData = await executeResponse.json();
            executionId = executeData.execution_id;
            result = {status: 'running', execution_id: executionId};

            // Compute a strict timeout: 2x execution limit (seconds -> ms)
            const execLimitSec = (k8sLimits?.execution_timeout || 5);
            const timeout = (2 * execLimitSec) * 1000;
            
            result = await new Promise((resolve, reject) => {
                // Use the SSE endpoint for real-time events from Kafka
                const eventSource = new EventSource(`/api/v1/events/executions/${executionId}`, {
                    withCredentials: true
                });
                
                let timeoutId = setTimeout(() => {
                    eventSource.close();
                    resolve({
                        status: 'timeout', 
                        errors: 'Execution timed out', 
                        execution_id: executionId
                    });
                }, timeout);
                
                eventSource.onopen = () => {
                    console.log('SSE connected for execution:', executionId);
                };
                
                eventSource.onmessage = async (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        const et = data?.event_type;
                        if (et === 'heartbeat' || et === 'connected') {
                            return;
                        }
                        console.log('Execution update:', data);
                        
                        // Update result with the latest status
                        if (data.event_type === 'result_stored' || data.type === 'result_stored') {
                            result = data.result;
                            clearTimeout(timeoutId);
                            eventSource.close();
                            resolve(result);
                        } else if (
                            data.event_type === 'execution_failed' || data.type === 'execution_failed' || data.status === 'failed' || data.status === 'error' ||
                            data.event_type === 'execution_timeout' || data.type === 'execution_timeout' || data.status === 'timeout'
                        ) {
                            // Close immediately on any terminal error
                            clearTimeout(timeoutId);
                            try { eventSource.close(); } catch {}
                            // Attempt one final fetch to ensure we return full payload
                            try {
                                const r = await fetchWithRetry(`/api/v1/result/${executionId}`, { method: 'GET' });
                                const finalData = await r.json();
                                resolve(finalData);
                            } catch {
                                resolve({ status: 'error', errors: data?.error || 'Execution failed', execution_id: executionId });
                            }
                        } else if (data.event_type === 'execution_completed' || data.type === 'execution_completed' || data.status === 'completed') {
                            result = { ...(result || {}), status: 'completed' };
                        } else if (data.event_type === 'execution_failed' || data.type === 'execution_failed' || data.status === 'failed' || data.status === 'error') {
                            result = { ...(result || {}), status: 'failed' };
                        } else if (data.event_type === 'execution_timeout' || data.type === 'execution_timeout' || data.status === 'timeout') {
                            result = { ...(result || {}), status: 'timeout' };
                        } else if (data.status) {
                            // Update intermediate status
                            result = {...result, status: data.status};
                        }
                    } catch (error) {
                        console.error('Error processing SSE event:', error);
                    }
                };
                
                eventSource.onerror = (error) => {
                    console.error('SSE error:', error);
                    clearTimeout(timeoutId);
                    eventSource.close();
                    
                    // Fall back to polling one final time to get the result
                    fetchWithRetry(`/api/v1/result/${executionId}`, {
                        method: 'GET'
                    }).then(response => response.json())
                      .then(data => resolve(data))
                      .catch(() => resolve({
                          status: 'error',
                          errors: 'Lost connection to execution stream',
                          execution_id: executionId
                      }));
                };
            });

            if (result?.status !== 'completed' && result?.status !== 'error' && result?.status !== 'failed' && result?.status !== 'timeout') {
                const timeoutMessage = `Execution timed out waiting for a final status.`;
                result = {status: 'error', errors: timeoutMessage, execution_id: executionId};
                addToast(timeoutMessage, 'warning');
            }

        } catch (err) {
            apiError = err.response?.data?.detail || "Error initiating script execution.";
            addToast(apiError, "error");
            result = {status: 'error', errors: apiError, execution_id: executionId};
            console.error("Error executing script:", err.response || err);
        } finally {
            executing = false;
        }
    }

    async function loadSavedScripts() {
        if (!authenticated) return;
        try {
            const data = await apiCall(`/api/v1/scripts`, {
                method: 'GET'
            }, {
                numOfAttempts: 3,
                maxDelay: 5000
            });
            // Ensure each script has a unique ID
            savedScripts = (data || []).map((script, index) => ({
                ...script,
                id: script.id || script._id || `temp_${index}_${Date.now()}`
            }));
        } catch (err) {
            console.error("Error loading saved scripts:", err);
            addToast("Failed to load saved scripts. You might need to log in again.", "error");
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
        const scriptValue = get(script);
        const langValue = get(selectedLang);
        const versionValue = get(selectedVersion);
        const currentIdValue = get(currentScriptId);
        let operation = currentIdValue ? 'update' : 'create';

        try {
            let data;
            if (operation === 'update') {
                try {
                    await apiCall(`/api/v1/scripts/${currentIdValue}`, {
                        method: 'PUT',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            name: nameValue, 
                            script: scriptValue,
                            lang: langValue,
                            lang_version: versionValue
                        })
                    }, {
                        numOfAttempts: 3,
                        maxDelay: 5000
                    });
                    addToast("Script updated successfully.", "success");
                } catch (updateErr) {
                    // If update fails with 404, the script doesn't exist anymore
                    // Clear the currentScriptId and fallback to create operation
                    if (updateErr.response?.status === 404) {
                        console.log('Script not found, falling back to create operation');
                        currentScriptId.set(null);
                        operation = 'create';
                        
                        data = await apiCall(`/api/v1/scripts`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({
                                name: nameValue, 
                                script: scriptValue,
                                lang: langValue,
                                lang_version: versionValue
                            })
                        }, {
                            numOfAttempts: 3,
                            maxDelay: 5000
                        });
                        currentScriptId.set(data.id);
                        addToast("Script saved successfully.", "success");
                    } else {
                        throw updateErr;
                    }
                }
            } else {
                data = await apiCall(`/api/v1/scripts`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        name: nameValue, 
                        script: scriptValue,
                        lang: langValue,
                        lang_version: versionValue
                    })
                }, {
                    numOfAttempts: 3,
                    maxDelay: 5000
                });
                currentScriptId.set(data.id);
                addToast("Script saved successfully.", "success");
            }
            await loadSavedScripts();
        } catch (err) {
            console.error(`Error ${operation === 'update' ? 'updating' : 'saving'} script:`, err.response || err);
            addToast(`Failed to ${operation} script. Please try again.`, "error");
            if (err.response?.status === 401) {
                handleLogout();
            }
        }
    }

    async function deleteScript(scriptIdToDelete) {
        if (!authenticated) return;
        const scriptToDelete = savedScripts.find(s => s.id === scriptIdToDelete);
        const confirmMessage = scriptToDelete
            ? `Are you sure you want to delete "${scriptToDelete.name}"?`
            : "Are you sure you want to delete this script?";

        if (!confirm(confirmMessage)) return;

        try {
            await apiCall(`/api/v1/scripts/${scriptIdToDelete}`, {
                method: 'DELETE'
            }, {
                numOfAttempts: 3,
                maxDelay: 5000
            });
            addToast("Script deleted successfully.", "success");
            if (get(currentScriptId) === scriptIdToDelete) {
                newScript();
            }
            await loadSavedScripts();
        } catch (err) {
            console.error("Error deleting script:", err.response || err);
            addToast("Failed to delete script.", "error");
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
        addToast("New script started.", "info");
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
            addToast("Only .py files are allowed.", "error");
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
                addToast(`Loaded script from ${file.name}`, "info");
            }
        };
        reader.onerror = () => {
            addToast("Failed to read the selected file.", "error");
        };
        reader.readAsText(file);
        event.target.value = null;
    }

    function handleLogout() {
        authLogout();
        navigate("/login");
        addToast("You have been logged out.", "info");
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
        if (showSavedScripts && authenticated) {
            loadSavedScripts();
        }
    }

    function loadExampleScript() {
        if (!editorView) return;
        const lang = get(selectedLang);
        const example = exampleScripts[lang];

        if (example) {
            const lines = example.split('\n');
            const firstLine = lines.find(line => line.trim().length > 0);
            const indentation = firstLine ? firstLine.match(/^\s*/)[0] : '';
            const cleanedScript = lines.map(line => line.startsWith(indentation) ? line.substring(indentation.length) : line).join('\n').trim();

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
        } else {
            addToast(`No example script available for ${lang}.`, "warning");
        }
    }

    async function copyExecutionId(executionId) {
        try {
            await navigator.clipboard.writeText(executionId);
            addToast("Execution ID copied to clipboard", "success");
        } catch (err) {
            console.error("Failed to copy execution ID:", err);
            addToast("Failed to copy execution ID", "error");
        }
    }

    async function copyOutput(output) {
        try {
            await navigator.clipboard.writeText(output);
            addToast("Output copied to clipboard", "success");
        } catch (err) {
            console.error("Failed to copy output:", err);
            addToast("Failed to copy output", "error");
        }
    }

    async function copyErrors(errors) {
        try {
            await navigator.clipboard.writeText(errors);
            addToast("Error text copied to clipboard", "success");
        } catch (err) {
            console.error("Failed to copy errors:", err);
            addToast("Failed to copy errors", "error");
        }
    }
</script>

<input type="file" accept=".py,text/x-python" bind:this={fileInput} class="hidden"/>

<div class="editor-grid-container space-y-4 md:space-y-0 md:gap-6" in:fade={{ duration: 300 }}>
    <header class="editor-header flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h2 class="text-xl sm:text-2xl font-semibold text-fg-default dark:text-dark-fg-default whitespace-nowrap">
            Code Editor
        </h2>
        {#if k8sLimits}
            <div class="relative shrink-0">
                <button class="btn btn-secondary-outline btn-sm inline-flex items-center space-x-1.5 w-full sm:w-auto justify-center"
                        on:click={toggleLimits} aria-expanded={showLimits}>
                    {@html resourceIcon}
                    <span>Resource Limits</span>
                    {#if showLimits} {@html chevronUpIcon} {:else} {@html chevronDownIcon} {/if}
                </button>
                {#if showLimits}
                    <div class="absolute right-0 top-full mt-2 w-64 sm:w-72 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-xl ring-1 ring-black/5 dark:ring-white/10 p-5 z-30 border border-border-default dark:border-dark-border-default"
                         transition:fly={{ y: 10, duration: 200 }}>
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

    <div class="editor-main-code flex flex-col rounded-lg overflow-hidden shadow-md border border-border-default dark:border-dark-border-default">
        <div class="editor-toolbar flex items-center justify-between px-3 py-1 bg-bg-default dark:bg-dark-bg-default border-b border-border-default dark:border-dark-border-default shrink-0">
            <div>
                <label for="scriptNameInput" class="sr-only">Script Name</label>
                <input id="scriptNameInput" type="text" class="form-input-bare"
                       placeholder="Unnamed Script" bind:value={$scriptName}/>
            </div>
            <div class="flex items-center space-x-2">
                 <button class="btn btn-secondary-outline btn-sm inline-flex items-center space-x-1.5"
                        on:click={loadExampleScript} title="Load an example script for the selected language">
                    {@html exampleIcon}
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
                    <button class="btn btn-primary inline-flex items-center space-x-2" on:click={loadExampleScript}>
                        {@html exampleIcon}
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
                        <p class="mt-3 text-sm font-medium text-primary-dark dark:text-primary-light">Executing script...</p>
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

                        {#if result.stdout}
                            <div class="output-section">
                                <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted mb-1 uppercase tracking-wider">
                                    Output:</h4>
                                <div class="relative">
                                    <pre class="output-pre custom-scrollbar">{@html sanitizeOutput(ansiConverter.toHtml(result.stdout || ''))}</pre>
                                    <div class="absolute bottom-2 right-2 group">
                                        <button class="inline-flex items-center p-1.5 rounded-lg text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors duration-150 cursor-pointer opacity-70 hover:opacity-100"
                                                aria-label="Copy output to clipboard"
                                                on:click={() => copyOutput(result.stdout)}>
                                            {@html copyIcon}
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
                                                on:click={() => copyErrors(result.stderr)}>
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
                    <button on:click={() => showLangOptions = !showLangOptions}
                            class="btn btn-secondary-outline btn-sm w-36 flex items-center justify-between text-left">
                        <span class="capitalize truncate">{$selectedLang} {$selectedVersion}</span>
                        <svg class="w-5 h-5 ml-2 shrink-0 text-fg-muted dark:text-dark-fg-muted transform transition-transform" class:-rotate-180={showLangOptions} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                        </svg>
                    </button>

                    {#if showLangOptions}
                        <div transition:fly={{ y: -5, duration: 150 }}
                             class="absolute bottom-full mb-2 w-36 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-xl ring-1 ring-black/5 dark:ring-white/10 z-30">
                            <ul class="py-1" on:mouseleave={() => hoveredLang = null}>
                                {#each Object.entries(supportedRuntimes) as [lang, versions] (lang)}
                                    <li class="relative" on:mouseenter={() => hoveredLang = lang}>
                                        <div class="flex justify-between items-center w-full px-3 py-2 text-sm text-fg-default dark:text-dark-fg-default">
                                            <span class="capitalize font-medium">{lang}</span>
                                            <svg class="w-4 h-4 text-fg-muted dark:text-dark-fg-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
                                        </div>

                                        {#if hoveredLang === lang && versions.length > 0}
                                            <div class="absolute left-full top-0 -mt-1 ml-1 w-20 bg-bg-alt dark:bg-dark-bg-alt rounded-lg shadow-lg ring-1 ring-black/5 dark:ring-white/10 z-40"
                                                 transition:fly={{ x: 5, duration: 100 }}>
                                                <ul class="py-1 max-h-60 overflow-y-auto custom-scrollbar">
                                                    {#each versions as version (version)}
                                                        <li>
                                                            <button on:click={() => { selectedLang.set(lang); selectedVersion.set(version); showLangOptions = false; hoveredLang = null; }}
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
                                {#if Object.keys(supportedRuntimes).length === 0}
                                    <li class="px-3 py-2 text-sm text-fg-muted dark:text-dark-fg-muted italic">No runtimes available</li>
                                {/if}
                            </ul>
                        </div>
                    {/if}
                </div>
                <button class="btn btn-primary btn-sm flex-grow sm:flex-grow-0 min-w-[130px]" on:click={executeScript}
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
                <div class="p-4 bg-bg-alt dark:bg-dark-bg-alt border border-border-default dark:border-dark-border-default rounded-lg flex space-x-4"
                     transition:slide={{ duration: 300, easing: (t) => 1 - Math.pow(1 - t, 3) }}>

                    <!-- Left Column: File Actions -->
                    <div class="w-1/2 space-y-3">
                        <h4 class="text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">
                            File Actions
                        </h4>
                        <div class="grid grid-cols-2 gap-2">
                            <button class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
                                    on:click={newScript} title="Start a new script">
                                {@html newFileIcon}<span>New</span>
                            </button>
                            <button class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
                                    on:click={() => fileInput.click()} title="Upload a file">
                                {@html uploadIcon}<span>Upload</span>
                            </button>
                            {#if authenticated}
                                <button class="btn btn-primary btn-sm inline-flex items-center justify-center space-x-1"
                                        on:click={saveScript} title="Save current script">
                                    {@html saveIcon}<span>Save</span>
                                </button>
                            {/if}
                            <button class="btn btn-secondary-outline btn-sm inline-flex items-center justify-center space-x-1"
                                    on:click={exportScript} title="Download current script">
                                {@html exportIcon}<span>Export</span>
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
                                        on:click={toggleSavedScripts}
                                        aria-expanded={showSavedScripts}
                                        title={showSavedScripts ? "Hide Saved Scripts" : "Show Saved Scripts"}>
                                    {@html listIcon}
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
                                                                on:click={() => loadScript(savedItem)}
                                                                title={`Load ${savedItem.name} (${savedItem.lang || 'python'} ${savedItem.lang_version || '3.11'})`}>
                                                            <div class="flex flex-col min-w-0">
                                                                <span class="truncate">{savedItem.name}</span>
                                                                <span class="text-xs text-fg-muted dark:text-dark-fg-muted font-normal capitalize">
                                                                    {savedItem.lang || 'python'} {savedItem.lang_version || '3.11'}
                                                                </span>
                                                            </div>
                                                        </button>
                                                        <button class="p-2 text-neutral-400 dark:text-neutral-500 hover:text-red-500 dark:hover:text-red-400 shrink-0 opacity-60 group-hover:opacity-100 transition-opacity duration-150 mr-1"
                                                                on:click|stopPropagation={() => deleteScript(savedItem.id)}
                                                                title={`Delete ${savedItem.name}`}>
                                                            <span class="sr-only">Delete</span>
                                                            {@html trashIcon}
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
