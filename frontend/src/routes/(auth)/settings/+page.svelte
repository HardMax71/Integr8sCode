<script lang="ts">
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import * as z from 'zod/mini';
    import { Control, Field, FieldErrors, Label } from 'formsnap';
    import {
        getUserSettingsApiV1UserSettingsGetOptions,
        getUserSettingsApiV1UserSettingsGetQueryKey,
        updateUserSettingsApiV1UserSettingsPutMutation,
        restoreSettingsApiV1UserSettingsRestorePostMutation,
        getSettingsHistoryApiV1UserSettingsHistoryGetOptions,
        getSettingsHistoryApiV1UserSettingsHistoryGetQueryKey,
        type UserSettings,
        Theme,
        zEditorSettingsInput,
        type EditorSettingsOutput,
        type NotificationSettingsOutput,
        zNotificationSettingsInput,
        zUserSettings,
    } from '#lib/api/index.ts';
    import { apiForm } from '#lib/forms.ts';
    import { setMode } from 'mode-watcher';
    import { toast } from 'svelte-sonner';
    import Spinner from '#components/Spinner.svelte';
    import Modal from '#components/Modal.svelte';
    import SettingsHistoryTable from '#components/settings/SettingsHistoryTable.svelte';
    import { Select } from 'bits-ui';
    import { Check, ChevronDown } from '@lucide/svelte';
    import { fieldTitle } from '#lib/formatters.ts';

    let activeTab = $state('general');
    let showHistory = $state(false);

    const tabs = [
        { id: 'general', label: 'General' },
        { id: 'editor', label: fieldTitle('editor') },
        { id: 'notifications', label: fieldTitle('notifications') },
    ];

    const themes = Object.values(Theme);

    const tabSizes: EditorSettingsOutput['tab_size'][] = [2, 4, 8];
    const editorToggles = [
        'use_tabs',
        'word_wrap',
        'show_line_numbers',
    ] as const satisfies (keyof EditorSettingsOutput)[];
    const notificationToggles = [
        'execution_completed',
        'execution_failed',
    ] as const satisfies (keyof NotificationSettingsOutput)[];

    const queryClient = useQueryClient();
    const settingsKey = getUserSettingsApiV1UserSettingsGetQueryKey();

    const settingsQuery = createQuery(() => getUserSettingsApiV1UserSettingsGetOptions());

    const historyQuery = createQuery(() => ({
        ...getSettingsHistoryApiV1UserSettingsHistoryGetOptions({ query: { limit: 10 } }),
        enabled: showHistory,
        staleTime: 30_000,
    }));
    let history = $derived(historyQuery.data?.history ?? []);

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

    const form = apiForm(
        z.object({
            theme: zUserSettings.shape.theme,
            notifications: zNotificationSettingsInput,
            editor: zEditorSettingsInput,
        }),
        {
            onUpdate: ({ form: submitted }) => {
                if (!submitted.valid) {
                    activeTab = tabs.find((tab) => tab.id in submitted.errors)?.id ?? activeTab;
                    return;
                }
                if (!isTainted()) {
                    toast.info('No changes to save');
                    return;
                }
                // Only the sections that changed, so the history lists only them
                const { theme, notifications, editor } = submitted.data;
                save.mutate({
                    body: {
                        theme: isTainted('theme') ? theme : null,
                        notifications: isTainted('notifications') ? notifications : null,
                        editor: isTainted('editor') ? editor : null,
                    },
                });
            },
        },
    );
    const { form: formData, constraints, enhance, isTainted, reset } = form;

    // Loading, saving and restoring put new settings in the query, and the form starts over from them
    $effect(() => {
        const loaded = settingsQuery.data;
        if (loaded)
            reset({ newState: { theme: loaded.theme, notifications: loaded.notifications, editor: loaded.editor } });
    });

    function restoreSettings(timestamp: string) {
        if (!confirm('Are you sure you want to restore settings to this point?')) return;
        restore.mutate({ body: { timestamp } });
    }
</script>

<svelte:head>
    <title>Settings - Integr8sCode</title>
    <meta
        name="description"
        content="Manage your Integr8sCode account settings, editor preferences, and notification configuration"
    />
</svelte:head>

<div class="page max-w-4xl">
    {#if settingsQuery.isPending}
        <div class="flex justify-center items-center h-64">
            <Spinner size="xlarge" />
        </div>
    {:else}
        <div class="hero-animate-fly-in" style="--fly-y: -20px; --fly-delay: 100ms;">
            <div class="flex justify-between items-center mb-8">
                <h1 class="lg:text-4xl">Settings</h1>

                <button type="button" onclick={() => (showHistory = true)} class="btn btn-secondary-outline btn-sm">
                    View History
                </button>
            </div>
        </div>

        <div class="flex gap-x-1 mb-6 bg-muted p-1 rounded-lg">
            {#each tabs as tab (tab.id)}
                <button
                    type="button"
                    class={[
                        'flex-1 px-4 py-2 text-sm font-medium rounded-md transition-colors',
                        activeTab === tab.id ? 'bg-surface shadow-xs text-accent' : 'text-fg-muted hover:text-fg',
                    ]}
                    onclick={() => (activeTab = tab.id)}
                >
                    {tab.label}
                </button>
            {/each}
        </div>

        <form method="post" use:enhance novalidate class="card">
            <div class="p-6">
                {#if activeTab === 'general'}
                    <h2 class="mb-4">General</h2>

                    <Field {form} name="theme">
                        <div class="field">
                            <Control>
                                {#snippet children({ props })}
                                    <Label>{fieldTitle('theme')}</Label>
                                    <Select.Root
                                        type="single"
                                        value={$formData.theme}
                                        onValueChange={(value) => {
                                            const picked = themes.find((t) => t === value);
                                            if (!picked) return;
                                            $formData.theme = picked;
                                            setMode(picked);
                                        }}
                                    >
                                        <Select.Trigger
                                            {...props}
                                            class="form-control-base flex items-center justify-between text-left group"
                                        >
                                            <span class="truncate">{$formData.theme}</span>
                                            <ChevronDown
                                                class="size-5 ml-2 shrink-0 text-fg-muted transition-transform group-data-[state=open]:-rotate-180"
                                            />
                                        </Select.Trigger>
                                        <Select.Portal>
                                            <Select.Content
                                                sideOffset={4}
                                                class="floating-panel w-(--bits-select-anchor-width)"
                                            >
                                                <Select.Viewport>
                                                    {#each themes as theme (theme)}
                                                        <Select.Item
                                                            value={theme}
                                                            label={theme}
                                                            class="floating-item justify-between"
                                                        >
                                                            {#snippet children({ selected })}
                                                                {theme}
                                                                {#if selected}<Check class="size-4 text-accent" />{/if}
                                                            {/snippet}
                                                        </Select.Item>
                                                    {/each}
                                                </Select.Viewport>
                                            </Select.Content>
                                        </Select.Portal>
                                    </Select.Root>
                                {/snippet}
                            </Control>
                        </div>
                    </Field>
                {:else if activeTab === 'editor'}
                    <h2 class="mb-4">
                        {fieldTitle('editor')}
                    </h2>

                    <div class="flex flex-wrap gap-4">
                        <Field {form} name="editor.font_size">
                            <Control>
                                {#snippet children({ props })}
                                    <div class="field flex-1 min-w-25">
                                        <Label>{fieldTitle('font_size')}</Label>
                                        <input
                                            {...props}
                                            {...$constraints.editor?.font_size}
                                            type="number"
                                            bind:value={$formData.editor.font_size}
                                            class="form-input-standard"
                                        />
                                        <FieldErrors class="mt-1" />
                                    </div>
                                {/snippet}
                            </Control>
                        </Field>

                        <Field {form} name="editor.tab_size">
                            <Control>
                                {#snippet children({ props })}
                                    <div class="field flex-1 min-w-25">
                                        <Label>{fieldTitle('tab_size')}</Label>
                                        <select
                                            {...props}
                                            bind:value={$formData.editor.tab_size}
                                            class="form-select-standard"
                                        >
                                            {#each tabSizes as size (size)}<option value={size}>{size}</option>{/each}
                                        </select>
                                    </div>
                                {/snippet}
                            </Control>
                        </Field>
                    </div>

                    <div class="my-6 border-t"></div>

                    <div class="space-y-3">
                        {#each editorToggles as key (key)}
                            <Field {form} name="editor.{key}">
                                <Control>
                                    {#snippet children({ props })}
                                        <Label class="settings-toggle">
                                            <span class="text-sm font-medium">{fieldTitle(key)}</span>
                                            <input {...props} type="checkbox" bind:checked={$formData.editor[key]} />
                                        </Label>
                                    {/snippet}
                                </Control>
                            </Field>
                        {/each}
                    </div>
                {:else if activeTab === 'notifications'}
                    <h2 class="mb-4">
                        {fieldTitle('notifications')}
                    </h2>

                    <h3 class="font-semibold mb-2">Notification Types</h3>
                    <div class="space-y-3">
                        {#each notificationToggles as key (key)}
                            <Field {form} name="notifications.{key}">
                                <Control>
                                    {#snippet children({ props })}
                                        <Label class="settings-toggle">
                                            <span class="text-sm font-medium">{fieldTitle(key)}</span>
                                            <input
                                                {...props}
                                                type="checkbox"
                                                bind:checked={$formData.notifications[key]}
                                            />
                                        </Label>
                                    {/snippet}
                                </Control>
                            </Field>
                        {/each}
                    </div>
                {/if}

                <div class="flex justify-end mt-6">
                    <button type="submit" class="btn btn-primary" disabled={save.isPending}>
                        {#if save.isPending}
                            <Spinner size="small" color="white" className="mr-2 inline-block" />
                            Saving...
                        {:else}
                            Save Settings
                        {/if}
                    </button>
                </div>
            </div>
        </form>
    {/if}
</div>

<Modal open={showHistory} title="Settings History" onClose={() => (showHistory = false)} size="lg">
    <div class="overflow-y-auto max-h-96">
        <SettingsHistoryTable {history} loading={historyQuery.isPending} onRestore={restoreSettings} />
    </div>
    {#snippet footer()}
        <button type="button" onclick={() => (showHistory = false)} class="btn btn-secondary-outline">Close</button>
    {/snippet}
</Modal>
