<script>
    import { onMount } from 'svelte';
    import { api } from '../lib/api';
    import { isAuthenticated, username } from '../stores/auth';
    import { theme as themeStore } from '../stores/theme';
    import { addToast } from '../stores/toastStore';
    import { get } from 'svelte/store';
    import { fly } from 'svelte/transition';
    import { setCachedSettings, updateCachedSetting } from '../lib/settings-cache';
    import Spinner from '../components/Spinner.svelte';
    
    let settings = null;
    let loading = true;
    let saving = false;
    let activeTab = 'general';
    let showHistory = false;
    let history = [];
    let historyLoading = false;
    
    // Dropdown states
    let showThemeDropdown = false;
    let showEditorThemeDropdown = false;
    
    // Force reactivity when formData changes
    $: formData && formData;
    
    // Debounce timer for auto-save
    let saveDebounceTimer = null;
    
    // Local state for form
    let formData = {
        theme: 'auto',
        notifications: {
            execution_completed: true,
            execution_failed: true,
            system_updates: true,
            security_alerts: true,
            channels: ['in_app']
        },
        editor: {
            theme: 'auto',
            font_size: 14,
            tab_size: 4,
            use_tabs: false,
            word_wrap: true,
            show_line_numbers: true,
        }
    };
    
    const tabs = [
        { id: 'general', label: 'General' },
        { id: 'editor', label: 'Editor' },
        { id: 'notifications', label: 'Notifications' }
    ];
    
    const themes = [
        { value: 'light', label: 'Light' },
        { value: 'dark', label: 'Dark' },
        { value: 'auto', label: 'Auto (System)' }
    ];
    
    
    const editorThemes = [
        { value: 'auto', label: 'Auto (Follow App Theme)' },
        { value: 'one-dark', label: 'One Dark' },
        { value: 'github', label: 'GitHub' }
    ];
    
    onMount(async () => {
        // First verify if user is authenticated
        if (!get(isAuthenticated)) {
            return;
        }
        
        await loadSettings();
        
        // Add click outside handler for dropdowns
        const handleClickOutside = (event) => {
            const target = event.target;
            if (!target.closest('.dropdown-container')) {
                showThemeDropdown = false;
                showEditorThemeDropdown = false;
            }
        };
        
        document.addEventListener('click', handleClickOutside);
        
        return () => {
            document.removeEventListener('click', handleClickOutside);
        };
    });
    
    async function loadSettings() {
        loading = true;
        try {
            // Set a timeout for loading settings
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout
            
            const response = await fetch('/api/v1/user/settings/', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include',
                signal: controller.signal
            }).finally(() => clearTimeout(timeoutId));
            
            if (!response.ok) {
                throw new Error('Failed to load settings');
            }
            
            settings = await response.json();
            
            // Cache the settings
            setCachedSettings(settings);
            
            // Update form data with proper defaults
            // Use current theme from store instead of backend to reflect local changes
            formData = {
                theme: $themeStore,
                notifications: {
                    execution_completed: settings.notifications?.execution_completed ?? true,
                    execution_failed: settings.notifications?.execution_failed ?? true,
                    system_updates: settings.notifications?.system_updates ?? true,
                    security_alerts: settings.notifications?.security_alerts ?? true,
                    channels: ['in_app']
                },
                editor: {
                    theme: settings.editor?.theme || 'auto',
                    font_size: settings.editor?.font_size || 14,
                    tab_size: settings.editor?.tab_size || 4,
                    use_tabs: settings.editor?.use_tabs ?? false,
                    word_wrap: settings.editor?.word_wrap ?? true,
                    show_line_numbers: settings.editor?.show_line_numbers ?? true,
                }
            };
        } catch (error) {
            if (error.name === 'AbortError') {
                addToast('Loading settings timed out. Please refresh the page.', 'error');
            } else {
                addToast('Failed to load settings. Using defaults.', 'error');
                // Use default settings if load fails
                settings = {};
            }
        } finally {
            loading = false;
        }
    }
    
    // Deep comparison helper for nested objects
    function deepEqual(obj1, obj2) {
        if (obj1 === obj2) return true;
        if (obj1 == null || obj2 == null) return false;
        if (typeof obj1 !== 'object' || typeof obj2 !== 'object') return obj1 === obj2;
        
        const keys1 = Object.keys(obj1);
        const keys2 = Object.keys(obj2);
        
        if (keys1.length !== keys2.length) return false;
        
        for (let key of keys1) {
            if (!keys2.includes(key)) return false;
            if (!deepEqual(obj1[key], obj2[key])) return false;
        }
        
        return true;
    }
    
    async function saveSettings() {
        saving = true;
        try {
            const updates = {};
            
            // Only include changed fields
            if (formData.theme !== settings.theme) updates.theme = formData.theme;
            
            // Compare nested objects with deep equality check
            if (!deepEqual(formData.notifications, settings.notifications)) {
                updates.notifications = formData.notifications;
            }
            if (!deepEqual(formData.editor, settings.editor)) {
                updates.editor = formData.editor;
            }
            if (!deepEqual(formData.preferences, settings.preferences)) {
                updates.preferences = formData.preferences;
            }
            
            if (Object.keys(updates).length === 0) {
                addToast('No changes to save', 'info');
                return;
            }
            
            // Send the update request
            const response = await api.put('/api/v1/user/settings/', updates);
            
            // Update local settings with the response
            settings = response;
            
            // Update cache with new settings
            setCachedSettings(settings);
            
            // Update formData with response to ensure consistency
            formData = {
                theme: settings.theme || 'auto',
                notifications: settings.notifications || formData.notifications,
                editor: settings.editor || formData.editor
            };
            
            // Theme is already saved by the theme store when changed in dropdown
            
            addToast('Settings saved successfully', 'success');
            
            // Don't reload settings after save - we already have the updated data
        } catch (error) {
            console.error('Settings save error:', error);
            addToast('Failed to save settings', 'error');
        } finally {
            saving = false;
        }
    }
    
    // Cache for history data
    let historyCache = null;
    let historyCacheTime = 0;
    const HISTORY_CACHE_DURATION = 30000; // Cache for 30 seconds
    
    async function loadHistory() {
        // Show the modal immediately with loading state
        showHistory = true;
        
        // Use cached history if available and recent
        if (historyCache && Date.now() - historyCacheTime < HISTORY_CACHE_DURATION) {
            history = historyCache;
            historyLoading = false;
            return;
        }
        
        history = [];
        historyLoading = true;
        
        try {
            // Set a timeout for the request to prevent long waits
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 second timeout
            
            const response = await fetch('/api/v1/user/settings/history?limit=10', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include',
                signal: controller.signal
            }).finally(() => clearTimeout(timeoutId));
            
            if (!response.ok) {
                throw new Error('Failed to fetch history');
            }
            
            const data = await response.json();
            history = data.history || [];
            
            // Process and sort history items (newest first)
            history = history
                .map(item => {
                    // Simplify field names by removing 'preferences.' prefix
                    let displayField = item.field;
                    if (displayField.startsWith('preferences.')) {
                        displayField = displayField.replace('preferences.', '');
                    }
                    
                    return {
                        ...item,
                        displayField,
                        isRestore: item.reason && item.reason.includes('restore')
                    };
                })
                .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
            
            // Cache the results
            historyCache = history;
            historyCacheTime = Date.now();
        } catch (error) {
            if (error.name === 'AbortError') {
                addToast('Loading history timed out. Please try again.', 'error');
            } else {
                addToast('Failed to load settings history', 'error');
            }
            history = [];
        } finally {
            historyLoading = false;
        }
    }
    
    async function restoreSettings(timestamp) {
        if (!confirm('Are you sure you want to restore settings to this point?')) {
            return;
        }
        
        try {
            settings = await api.post('/api/v1/user/settings/restore', {
                timestamp,
                reason: 'User requested restore'
            });
            
            // Invalidate cache since settings have changed
            historyCache = null;
            historyCacheTime = 0;
            
            await loadSettings();
            
            // Apply restored theme
            if (settings.theme) {
                themeStore.set(settings.theme);
            }
            
            showHistory = false;
            addToast('Settings restored successfully', 'success');
        } catch (error) {
            addToast('Failed to restore settings', 'error');
        }
    }
    
    function formatTimestamp(ts) {
        // Support ISO 8601 strings or epoch seconds/ms
        let date;
        if (typeof ts === 'string') {
            date = new Date(ts);
        } else if (typeof ts === 'number') {
            // Heuristic: seconds vs ms
            date = ts < 1e12 ? new Date(ts * 1000) : new Date(ts);
        } else {
            return '';
        }
        if (isNaN(date.getTime())) return '';
        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = date.getFullYear();
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${day}/${month}/${year} ${hours}:${minutes}`;
    }
</script>

<div class="min-h-screen bg-bg-default dark:bg-dark-bg-default">
    <div class="container mx-auto px-4 py-8 max-w-4xl">
    {#if loading}
        <div class="flex justify-center items-center h-64">
            <Spinner size="xlarge" />
        </div>
    {:else}
        <div class="flex justify-between items-center mb-8">
            <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">Settings</h1>
            
            <button
                on:click={loadHistory}
                class="btn btn-secondary-outline btn-sm"
            >
                View History
            </button>
        </div>
        
        <div class="flex space-x-1 mb-6 bg-neutral-100 dark:bg-neutral-800 p-1 rounded-lg">
            {#each tabs as tab}
                <button
                    class="flex-1 px-4 py-2 text-sm font-medium rounded-md transition-all duration-200"
                    class:bg-white={activeTab === tab.id}
                    class:dark:bg-neutral-700={activeTab === tab.id}
                    class:shadow-xs={activeTab === tab.id}
                    class:text-primary={activeTab === tab.id}
                    class:dark:text-primary-light={activeTab === tab.id}
                    class:text-fg-muted={activeTab !== tab.id}
                    class:dark:text-dark-fg-muted={activeTab !== tab.id}
                    class:hover:text-fg-default={activeTab !== tab.id}
                    class:dark:hover:text-dark-fg-default={activeTab !== tab.id}
                    on:click={() => activeTab = tab.id}
                >
                    {tab.label}
                </button>
            {/each}
        </div>
        
        <div class="card">
            <div class="p-6">
                {#if activeTab === 'general'}
                    <h2 class="text-xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">General Settings</h2>
                    
                    <div class="form-control">
                        <label for="theme-select" class="block mb-2">
                            <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Theme</span>
                        </label>
                        <div class="relative dropdown-container">
                            <button id="theme-select" on:click={() => showThemeDropdown = !showThemeDropdown}
                                    class="form-dropdown-button"
                                    aria-expanded={showThemeDropdown}>
                                <span class="truncate">{themes.find(t => t.value === formData.theme)?.label || 'Select theme'}</span>
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                                </svg>
                            </button>

                            {#if showThemeDropdown}
                                <div transition:fly={{ y: 5, duration: 150 }}
                                     class="form-dropdown-menu">
                                    <ul class="py-1">
                                        {#each themes as theme}
                                            <li>
                                                <button on:click={() => { 
                                    formData.theme = theme.value; 
                                    showThemeDropdown = false;
                                    // Apply theme immediately if it's the theme setting
                                    if (theme.value) {
                                        themeStore.set(theme.value);
                                    }
                                }}
                                                        class:selected={formData.theme === theme.value}
                                                >
                                                    {theme.label}
                                                </button>
                                            </li>
                                        {/each}
                                    </ul>
                                </div>
                            {/if}
                        </div>
                    </div>
                    
                {:else if activeTab === 'editor'}
                    <h2 class="text-xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Editor Settings</h2>
                    
                    <div class="flex flex-wrap gap-4">
                        <div class="form-control flex-1 min-w-[150px]">
                            <label for="editor-theme-select" class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Editor Theme</span>
                            </label>
                            <div class="relative dropdown-container">
                                <button id="editor-theme-select" on:click={() => showEditorThemeDropdown = !showEditorThemeDropdown}
                                        class="form-dropdown-button"
                                        aria-expanded={showEditorThemeDropdown}>
                                    <span class="truncate">{editorThemes.find(t => t.value === formData.editor.theme)?.label || 'Select theme'}</span>
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                                    </svg>
                                </button>

                                {#if showEditorThemeDropdown}
                                    <div transition:fly={{ y: 5, duration: 150 }}
                                         class="form-dropdown-menu">
                                        <ul class="py-1">
                                            {#each editorThemes as theme}
                                                <li>
                                                    <button on:click={() => { formData.editor.theme = theme.value; showEditorThemeDropdown = false; }}
                                                            class:selected={formData.editor.theme === theme.value}
                                                    >
                                                        {theme.label}
                                                    </button>
                                                </li>
                                            {/each}
                                        </ul>
                                    </div>
                                {/if}
                            </div>
                        </div>
                        
                        <div class="form-control flex-1 min-w-[100px]">
                            <label for="font-size" class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Font Size</span>
                            </label>
                            <input
                                id="font-size"
                                type="number"
                                bind:value={formData.editor.font_size}
                                min="10"
                                max="24"
                                class="form-input-number"
                            />
                        </div>
                        
                        <div class="form-control flex-1 min-w-[100px]">
                            <label for="tab-size" class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Tab Size</span>
                            </label>
                            <input
                                id="tab-size"
                                type="number"
                                bind:value={formData.editor.tab_size}
                                min="2"
                                max="8"
                                class="form-input-number"
                            />
                        </div>
                    </div>
                    
                    <div class="my-6 border-t border-border-default dark:border-dark-border-default"></div>
                    
                    <div class="space-y-3">
                        <label class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">
                            <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Use Tabs</span>
                            <input
                                type="checkbox"
                                bind:checked={formData.editor.use_tabs}
                                class="form-checkbox-standard"
                            />
                        </label>
                        
                        <label class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">
                            <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Word Wrap</span>
                            <input
                                type="checkbox"
                                bind:checked={formData.editor.word_wrap}
                                class="form-checkbox-standard"
                            />
                        </label>
                        
                        <label class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">
                            <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Show Line Numbers</span>
                            <input
                                type="checkbox"
                                bind:checked={formData.editor.show_line_numbers}
                                class="form-checkbox-standard"
                            />
                        </label>
                    </div>
                    
                {:else if activeTab === 'notifications'}
                    <h2 class="text-xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">Notification Settings</h2>
                    
                    <div class="space-y-4">
                        <div>
                            <h3 class="font-semibold mb-2">Notification Types</h3>
                            <div class="space-y-3">
                                <label class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">
                                    <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Execution Completed</span>
                                    <input
                                        type="checkbox"
                                        bind:checked={formData.notifications.execution_completed}
                                        class="form-checkbox-standard"
                                    />
                                </label>
                                
                                <label class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">
                                    <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Execution Failed</span>
                                    <input
                                        type="checkbox"
                                        bind:checked={formData.notifications.execution_failed}
                                        class="form-checkbox-standard"
                                    />
                                </label>
                                
                                <label class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">
                                    <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">System Updates</span>
                                    <input
                                        type="checkbox"
                                        bind:checked={formData.notifications.system_updates}
                                        class="form-checkbox-standard"
                                    />
                                </label>
                                
                                <label class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">
                                    <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Security Alerts</span>
                                    <input
                                        type="checkbox"
                                        bind:checked={formData.notifications.security_alerts}
                                        class="form-checkbox-standard"
                                    />
                                </label>
                            </div>
                        </div>
                        
                        
                    </div>
                {/if}
                
                <div class="flex justify-end mt-6">
                    <button
                        on:click={saveSettings}
                        class="btn btn-primary"
                        disabled={saving}
                    >
                        {#if saving}
                            <Spinner size="small" color="white" className="mr-2 inline-block" />
                            Saving...
                        {:else}
                            Save Settings
                        {/if}
                    </button>
                </div>
            </div>
        </div>
    {/if}
    </div>
</div>

{#if showHistory}
    <div class="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:p-0">
        <button class="fixed inset-0 bg-black/50 cursor-default" on:click={() => showHistory = false} aria-label="Close modal"></button>
        <div class="relative inline-block align-bottom bg-bg-alt dark:bg-dark-bg-alt rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-4xl sm:w-full">
            <div class="p-6">
                <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">Settings History</h3>
                
                <div class="overflow-y-auto max-h-96">
                    <table class="w-full">
                        <thead class="bg-neutral-50 dark:bg-neutral-900 sticky top-0">
                            <tr>
                                <th class="px-4 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider w-36">Date</th>
                                <th class="px-4 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider w-32">Field</th>
                                <th class="px-4 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Change</th>
                                <th class="px-4 py-2 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider w-20"></th>
                            </tr>
                        </thead>
                        <tbody>
                            {#if historyLoading}
                                <tr>
                                    <td colspan="4" class="px-4 py-8 text-center text-fg-muted dark:text-dark-fg-muted">
                                        <Spinner size="large" className="mx-auto" />
                                    </td>
                                </tr>
                            {:else if history.length === 0}
                                <tr>
                                    <td colspan="4" class="px-4 py-8 text-center text-fg-muted dark:text-dark-fg-muted">
                                        No settings changes recorded yet. Make some changes to your settings to see history.
                                    </td>
                                </tr>
                            {:else}
                                {#each history as item}
                                    <tr class="border-b border-border-default dark:border-dark-border-default hover:bg-neutral-50 dark:hover:bg-neutral-800">
                                        <td class="px-4 py-2 text-sm text-fg-default dark:text-dark-fg-default whitespace-nowrap">{formatTimestamp(item.timestamp)}</td>
                                        <td class="px-4 py-2 text-sm text-fg-default dark:text-dark-fg-default">{item.displayField}</td>
                                        <td class="px-4 py-2 text-sm font-mono text-fg-muted dark:text-dark-fg-muted">
                                            <div class="flex flex-wrap items-center gap-1">
                                                <span class="text-red-600 dark:text-red-400 break-all">{typeof item.old_value === 'object' ? JSON.stringify(item.old_value) : item.old_value}</span>
                                                <span class="mx-1">→</span>
                                                <span class="text-green-600 dark:text-green-400 break-all">{typeof item.new_value === 'object' ? JSON.stringify(item.new_value) : item.new_value}</span>
                                            </div>
                                        </td>
                                        <td class="px-4 py-2">
                                            <button
                                                on:click={() => restoreSettings(item.timestamp)}
                                                class="btn btn-ghost btn-xs"
                                            >
                                                Restore
                                            </button>
                                        </td>
                                    </tr>
                                {/each}
                            {/if}
                        </tbody>
                    </table>
                </div>
            
                <div class="mt-5 sm:mt-6 flex justify-end">
                    <button
                        on:click={() => showHistory = false}
                        class="btn btn-secondary-outline"
                    >
                        Close
                    </button>
                </div>
            </div>
        </div>
    </div>
{/if}
