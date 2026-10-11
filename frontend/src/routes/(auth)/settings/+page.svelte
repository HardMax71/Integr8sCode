<script lang="ts">
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import {
        getUserSettingsApiV1UserSettingsGetOptions,
        getUserSettingsApiV1UserSettingsGetQueryKey,
        updateUserSettingsApiV1UserSettingsPutMutation,
        restoreSettingsApiV1UserSettingsRestorePostMutation,
        getSettingsHistoryApiV1UserSettingsHistoryGetOptions,
        getSettingsHistoryApiV1UserSettingsHistoryGetQueryKey,
        type UserSettings,
        type UserSettingsUpdate,
        Theme,
        zEditorSettingsInput,
        zNotificationSettingsInput,
        zUserSettings,
    } from '#lib/api/index.ts';
    import { authStore } from '#stores/auth.svelte.ts';
    import { setTheme } from '#stores/theme.svelte.ts';
    import { toast } from 'svelte-sonner';
    import Spinner from '#components/Spinner.svelte';
    import Modal from '#components/Modal.svelte';
    import SettingsHistoryTable from '#components/settings/SettingsHistoryTable.svelte';
    import { Select } from 'bits-ui';
    import { Check, ChevronDown } from '@lucide/svelte';
    import { formatTimestamp } from '#lib/formatters.ts';

    type SettingsForm = Pick<UserSettings, 'theme' | 'notifications' | 'editor'>;

    let activeTab = $state('general');
    let showHistory = $state(false);

    const tabs = [
        { id: 'general', label: 'General' },
        { id: 'editor', label: 'Editor' },
        { id: 'notifications', label: 'Notifications' },
    ];

    const themeLabels: Record<Theme, string> = { light: 'Light', dark: 'Dark', auto: 'Auto (System)' };
    const themes = Object.values(Theme).map((value) => ({ value, label: themeLabels[value] }));

    function toForm(data: UserSettings): SettingsForm {
        return {
            theme: data.theme,
            notifications: { ...data.notifications },
            editor: { ...data.editor },
        };
    }

    const queryClient = useQueryClient();
    const settingsKey = getUserSettingsApiV1UserSettingsGetQueryKey();

    const settingsQuery = createQuery(() => ({
        ...getUserSettingsApiV1UserSettingsGetOptions(),
        enabled: authStore.isAuthenticated === true,
    }));

    let loaded = $derived(settingsQuery.data);
    // Edits go to a copy of the loaded settings (the API's defaults until then), which an unchanged refetch keeps
    let formData = $derived.by(() => {
        const draft = $state<SettingsForm>(
            loaded
                ? toForm(loaded)
                : {
                      theme: zUserSettings.shape.theme.parse(undefined),
                      notifications: zNotificationSettingsInput.parse({}),
                      editor: zEditorSettingsInput.parse({}),
                  },
        );
        return draft;
    });

    const historyQuery = createQuery(() => ({
        ...getSettingsHistoryApiV1UserSettingsHistoryGetOptions({ query: { limit: 10 } }),
        enabled: showHistory,
        staleTime: 30_000,
    }));
    let history = $derived(
        [...(historyQuery.data?.history ?? [])].sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime()),
    );

    function storeSettings(data: UserSettings): void {
        queryClient.setQueryData(settingsKey, data);
        void queryClient.invalidateQueries({ queryKey: getSettingsHistoryApiV1UserSettingsHistoryGetQueryKey() });
    }

    const save = createMutation(() => ({
        ...updateUserSettingsApiV1UserSettingsPutMutation(),
        onSuccess: (data) => {
            storeSettings(data);
            toast.success('Settings saved successfully');
        },
    }));

    const restore = createMutation(() => ({
        ...restoreSettingsApiV1UserSettingsRestorePostMutation(),
        onSuccess: (data) => {
            storeSettings(data);
            showHistory = false;
            toast.success('Settings restored successfully');
        },
    }));

    function saveSettings() {
        const current = $state.snapshot(formData);
        const saved = loaded ? toForm(loaded) : null;
        if (!saved || JSON.stringify(current) === JSON.stringify(saved)) {
            toast.info('No changes to save');
            return;
        }

        const updates: UserSettingsUpdate = {};
        if (current.theme !== saved.theme) updates.theme = current.theme;
        if (JSON.stringify(current.notifications) !== JSON.stringify(saved.notifications))
            updates.notifications = current.notifications;
        if (JSON.stringify(current.editor) !== JSON.stringify(saved.editor)) updates.editor = current.editor;
        save.mutate({ body: updates });
    }

    function restoreSettings(timestamp: Date) {
        if (!confirm('Are you sure you want to restore settings to this point?')) return;
        restore.mutate({ body: { timestamp, reason: 'User requested restore' } });
    }
</script>

<svelte:head>
    <title>Settings - Integr8sCode</title>
    <meta
        name="description"
        content="Manage your Integr8sCode account settings, editor preferences, and notification configuration"
    />
</svelte:head>

<div class="min-h-screen bg-bg-default dark:bg-dark-bg-default">
    <div class="container mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12 lg:py-16 max-w-4xl">
        {#if settingsQuery.isPending && authStore.isAuthenticated}
            <div class="flex justify-center items-center h-64">
                <Spinner size="xlarge" />
            </div>
        {:else}
            <div class="hero-animate-fly-in" style="--fly-y: -20px; --fly-delay: 100ms;">
                <div class="flex justify-between items-center mb-8">
                    <h1 class="text-2xl sm:text-3xl lg:text-4xl font-bold text-fg-default dark:text-dark-fg-default">
                        Settings
                    </h1>

                    <button type="button" onclick={() => (showHistory = true)} class="btn btn-secondary-outline btn-sm">
                        View History
                    </button>
                </div>
            </div>

            <div class="flex space-x-1 mb-6 bg-neutral-100 dark:bg-neutral-800 p-1 rounded-lg">
                {#each tabs as tab}
                    <button
                        type="button"
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
                        onclick={() => (activeTab = tab.id)}
                    >
                        {tab.label}
                    </button>
                {/each}
            </div>

            <div class="card">
                <div class="p-6">
                    {#if activeTab === 'general'}
                        <h2 class="text-xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">
                            General Settings
                        </h2>

                        <div class="form-control">
                            <label for="theme-select" class="block mb-2">
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Theme</span>
                            </label>
                            <Select.Root
                                type="single"
                                value={formData.theme}
                                onValueChange={(value) => {
                                    const picked = themes.find((t) => t.value === value)?.value;
                                    if (!picked) return;
                                    formData.theme = picked;
                                    setTheme(picked);
                                }}
                            >
                                <Select.Trigger
                                    id="theme-select"
                                    class="form-control-base flex items-center justify-between text-left group"
                                >
                                    <span class="truncate">{themeLabels[formData.theme]}</span>
                                    <ChevronDown
                                        class="w-5 h-5 ml-2 shrink-0 text-fg-muted dark:text-dark-fg-muted transition-transform group-data-[state=open]:-rotate-180"
                                    />
                                </Select.Trigger>
                                <Select.Portal>
                                    <Select.Content
                                        sideOffset={4}
                                        class="floating-panel w-(--bits-select-anchor-width)"
                                    >
                                        <Select.Viewport>
                                            {#each themes as theme (theme.value)}
                                                <Select.Item
                                                    value={theme.value}
                                                    label={theme.label}
                                                    class="floating-item justify-between"
                                                >
                                                    {#snippet children({ selected })}
                                                        {theme.label}
                                                        {#if selected}<Check class="w-4 h-4 text-primary" />{/if}
                                                    {/snippet}
                                                </Select.Item>
                                            {/each}
                                        </Select.Viewport>
                                    </Select.Content>
                                </Select.Portal>
                            </Select.Root>
                        </div>
                    {:else if activeTab === 'editor'}
                        <h2 class="text-xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">
                            Editor Settings
                        </h2>

                        <div class="flex flex-wrap gap-4">
                            <div class="form-control flex-1 min-w-[100px]">
                                <label for="font-size" class="block mb-2">
                                    <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default"
                                        >Font Size</span
                                    >
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
                                    <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default"
                                        >Tab Size</span
                                    >
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
                            <label
                                class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
                            >
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default"
                                    >Use Tabs</span
                                >
                                <input
                                    type="checkbox"
                                    bind:checked={formData.editor.use_tabs}
                                    class="form-checkbox-standard"
                                />
                            </label>

                            <label
                                class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
                            >
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default"
                                    >Word Wrap</span
                                >
                                <input
                                    type="checkbox"
                                    bind:checked={formData.editor.word_wrap}
                                    class="form-checkbox-standard"
                                />
                            </label>

                            <label
                                class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
                            >
                                <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default"
                                    >Show Line Numbers</span
                                >
                                <input
                                    type="checkbox"
                                    bind:checked={formData.editor.show_line_numbers}
                                    class="form-checkbox-standard"
                                />
                            </label>
                        </div>
                    {:else if activeTab === 'notifications'}
                        <h2 class="text-xl font-semibold text-fg-default dark:text-dark-fg-default mb-4">
                            Notification Settings
                        </h2>

                        <div class="space-y-4">
                            <div>
                                <h3 class="font-semibold mb-2">Notification Types</h3>
                                <div class="space-y-3">
                                    <label
                                        class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
                                    >
                                        <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default"
                                            >Execution Completed</span
                                        >
                                        <input
                                            type="checkbox"
                                            bind:checked={formData.notifications.execution_completed}
                                            class="form-checkbox-standard"
                                        />
                                    </label>

                                    <label
                                        class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
                                    >
                                        <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default"
                                            >Execution Failed</span
                                        >
                                        <input
                                            type="checkbox"
                                            bind:checked={formData.notifications.execution_failed}
                                            class="form-checkbox-standard"
                                        />
                                    </label>

                                    <label
                                        class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
                                    >
                                        <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default"
                                            >System Updates</span
                                        >
                                        <input
                                            type="checkbox"
                                            bind:checked={formData.notifications.system_updates}
                                            class="form-checkbox-standard"
                                        />
                                    </label>

                                    <label
                                        class="flex items-center justify-between cursor-pointer p-3 rounded-lg hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
                                    >
                                        <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default"
                                            >Security Alerts</span
                                        >
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
                        <button type="button" onclick={saveSettings} class="btn btn-primary" disabled={save.isPending}>
                            {#if save.isPending}
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

<Modal open={showHistory} title="Settings History" onClose={() => (showHistory = false)} size="lg">
    {#snippet children()}
        <div class="overflow-y-auto max-h-96">
            <SettingsHistoryTable {history} loading={historyQuery.isPending} onRestore={restoreSettings} />
        </div>
    {/snippet}
    {#snippet footer()}
        <button type="button" onclick={() => (showHistory = false)} class="btn btn-secondary-outline">Close</button>
    {/snippet}
</Modal>
