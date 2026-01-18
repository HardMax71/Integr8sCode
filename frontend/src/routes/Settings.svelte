<script lang="ts">
    import { onMount } from 'svelte';
    import {
        getUserSettingsApiV1UserSettingsGet,
        updateUserSettingsApiV1UserSettingsPut,
        restoreSettingsApiV1UserSettingsRestorePost,
        getSettingsHistoryApiV1UserSettingsHistoryGet,
    } from '$lib/api';
    import { isAuthenticated, username } from '$stores/auth';
    import { theme as themeStore, setTheme } from '$stores/theme';
    import { addToast } from '$stores/toastStore';
    import { get } from 'svelte/store';
    import { fly } from 'svelte/transition';
    import { setUserSettings } from '$stores/userSettings';
    import Spinner from '$components/Spinner.svelte';
    import { ChevronDown } from '@lucide/svelte';

    let loading = $state(true);
    let saving = $state(false);
    let activeTab = $state('general');
    let showHistory = $state(false);
    let history = $state<any[]>([]);
    let historyLoading = $state(false);

    // Dropdown states
    let showThemeDropdown = $state(false);
    let showEditorThemeDropdown = $state(false);

    // Form state (single source of truth for UI)
    let formData = $state({
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
    });

    // Snapshot for change detection (JSON string - no reference issues)
    let savedSnapshot = $state('');
    
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
    
    onMount(() => {
        // First verify if user is authenticated
        if (!get(isAuthenticated)) {
            return;
        }

        loadSettings();

        // Add click outside handler for dropdowns
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Element | null;
            if (!target?.closest('.dropdown-container')) {
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
            const { data, error } = await getUserSettingsApiV1UserSettingsGet({});
            if (error) throw error;

            setUserSettings(data ?? null);

            if (data) {
                formData = {
                    theme: data.theme || 'auto',
                    notifications: {
                        execution_completed: data.notifications?.execution_completed ?? true,
                        execution_failed: data.notifications?.execution_failed ?? true,
                        system_updates: data.notifications?.system_updates ?? true,
                        security_alerts: data.notifications?.security_alerts ?? true,
                        channels: [...(data.notifications?.channels || ['in_app'])]
                    },
                    editor: {
                        theme: data.editor?.theme || 'auto',
                        font_size: data.editor?.font_size || 14,
                        tab_size: data.editor?.tab_size || 4,
                        use_tabs: data.editor?.use_tabs ?? false,
                        word_wrap: data.editor?.word_wrap ?? true,
                        show_line_numbers: data.editor?.show_line_numbers ?? true,
                    }
                };
            }
            savedSnapshot = JSON.stringify(formData);
        } catch (err) {
            console.error('Failed to load settings:', err);
            addToast('Failed to load settings. Using defaults.', 'error');
        } finally {
            loading = false;
        }
    }
    
    async function saveSettings() {
        const currentState = JSON.stringify(formData);
        if (currentState === savedSnapshot) {
            addToast('No changes to save', 'info');
            return;
        }

        saving = true;
        try {
            const original = JSON.parse(savedSnapshot);
            const updates: Record<string, any> = {};

            if (formData.theme !== original.theme) {
                updates.theme = formData.theme;
            }
            if (JSON.stringify(formData.notifications) !== JSON.stringify(original.notifications)) {
                updates.notifications = formData.notifications;
            }
            if (JSON.stringify(formData.editor) !== JSON.stringify(original.editor)) {
                updates.editor = formData.editor;
            }

            const { data, error } = await updateUserSettingsApiV1UserSettingsPut({ body: updates });
            if (error) throw error;

            setUserSettings(data);

            formData = {
                theme: data.theme || 'auto',
                notifications: {
                    execution_completed: data.notifications?.execution_completed ?? true,
                    execution_failed: data.notifications?.execution_failed ?? true,
                    system_updates: data.notifications?.system_updates ?? true,
                    security_alerts: data.notifications?.security_alerts ?? true,
                    channels: [...(data.notifications?.channels || ['in_app'])]
                },
                editor: {
                    theme: data.editor?.theme || 'auto',
                    font_size: data.editor?.font_size || 14,
                    tab_size: data.editor?.tab_size || 4,
                    use_tabs: data.editor?.use_tabs ?? false,
                    word_wrap: data.editor?.word_wrap ?? true,
                    show_line_numbers: data.editor?.show_line_numbers ?? true,
                }
            };
            savedSnapshot = JSON.stringify(formData);

            addToast('Settings saved successfully', 'success');
        } catch (err) {
            console.error('Settings save error:', err);
            addToast('Failed to save settings', 'error');
        } finally {
            saving = false;
        }
    }
    
    // Cache for history data
    let historyCache: typeof history | null = null;
    let historyCacheTime = 0;
    const HISTORY_CACHE_DURATION = 30000; // Cache for 30 seconds

    async function loadHistory() {
        showHistory = true;

        if (historyCache && Date.now() - historyCacheTime < HISTORY_CACHE_DURATION) {
            history = historyCache;
            historyLoading = false;
            return;
        }

        history = [];
        historyLoading = true;

        try {
            const { data, error } = await getSettingsHistoryApiV1UserSettingsHistoryGet({ query: { limit: 10 } });
            if (error) throw error;

            history = (data?.history || [])
                .map(item => ({
                    ...item,
                    displayField: item.field,
                    isRestore: item.reason?.includes('restore')
                }))
                .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

            historyCache = history;
            historyCacheTime = Date.now();
        } catch (err) {
            console.error('Failed to load settings history:', err);
            addToast('Failed to load settings history', 'error');
            history = [];
        } finally {
            historyLoading = false;
        }
    }
    
    async function restoreSettings(timestamp: string): Promise<void> {
        if (!confirm('Are you sure you want to restore settings to this point?')) {
            return;
        }

        try {
            const { data, error } = await restoreSettingsApiV1UserSettingsRestorePost({
                body: { timestamp, reason: 'User requested restore' }
            });
            if (error) throw error;

            historyCache = null;
            historyCacheTime = 0;

            await loadSettings();

            if (data.theme) {
                setTheme(data.theme);
            }

            showHistory = false;
            addToast('Settings restored successfully', 'success');
        } catch (err) {
            console.error('Failed to restore settings:', err);
            addToast('Failed to restore settings', 'error');
        }
    }
    
    function formatTimestamp(ts: string | number): string {
        // Support ISO 8601 strings or epoch seconds/ms
        let date: Date;
        if (typeof ts === 'string') {
            date = new Date(ts);
        } else {
            // Heuristic: seconds vs ms
            date = ts < 1e12 ? new Date(ts * 1000) : new Date(ts);
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
                onclick={loadHistory}
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
                    onclick={() => activeTab = tab.id}
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
                            <button id="theme-select" onclick={() => showThemeDropdown = !showThemeDropdown}
                                    class="form-dropdown-button"
                                    aria-expanded={showThemeDropdown}>
                                <span class="truncate">{themes.find(t => t.value === formData.theme)?.label || 'Select theme'}</span>
                                <ChevronDown class="w-5 h-5" />
                            </button>

                            {#if showThemeDropdown}
                                <div transition:fly={{ y: 5, duration: 150 }}
                                     class="form-dropdown-menu">
                                    <ul class="py-1">
                                        {#each themes as theme}
                                            <li>
                                                <button onclick={() => {
                                    formData.theme = theme.value;
                                    showThemeDropdown = false;
                                    if (theme.value) {
                                        setTheme(theme.value as 'light' | 'dark' | 'auto');
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
                                <button id="editor-theme-select" onclick={() => showEditorThemeDropdown = !showEditorThemeDropdown}
                                        class="form-dropdown-button"
                                        aria-expanded={showEditorThemeDropdown}>
                                    <span class="truncate">{editorThemes.find(t => t.value === formData.editor.theme)?.label || 'Select theme'}</span>
                                    <ChevronDown class="w-5 h-5" />
                                </button>

                                {#if showEditorThemeDropdown}
                                    <div transition:fly={{ y: 5, duration: 150 }}
                                         class="form-dropdown-menu">
                                        <ul class="py-1">
                                            {#each editorThemes as theme}
                                                <li>
                                                    <button onclick={() => { formData.editor.theme = theme.value; showEditorThemeDropdown = false; }}
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
                        onclick={saveSettings}
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
        <button class="fixed inset-0 bg-black/50 cursor-default" onclick={() => showHistory = false} aria-label="Close modal"></button>
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
                                                onclick={() => restoreSettings(item.timestamp)}
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
                        onclick={() => showHistory = false}
                        class="btn btn-secondary-outline"
                    >
                        Close
                    </button>
                </div>
            </div>
        </div>
    </div>
{/if}
