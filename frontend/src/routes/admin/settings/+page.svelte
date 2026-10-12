<script lang="ts">
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import {
        getSystemSettingsApiV1AdminSettingsGetOptions,
        getSystemSettingsApiV1AdminSettingsGetQueryKey,
        updateSystemSettingsApiV1AdminSettingsPutMutation,
        resetSystemSettingsApiV1AdminSettingsResetPostMutation,
        LogLevel,
        type SystemSettingsSchemaInput,
        type SystemSettingsSchemaOutput,
        zSystemSettingsSchemaInput,
    } from '#lib/api/index.ts';
    import { firstIssue } from '#lib/validation.ts';
    import { fieldTitle, formatBoolean } from '#lib/formatters.ts';
    import * as z from 'zod/mini';
    import { toast } from 'svelte-sonner';
    import Spinner from '#components/Spinner.svelte';

    const fieldSchemas = z.toJSONSchema(zSystemSettingsSchemaInput, { io: 'input' }).properties ?? {};
    const DEFAULTS = zSystemSettingsSchemaInput.parse({});

    // min and max for a numeric input, taken from the API's validation rules
    function bounds(field: keyof SystemSettingsSchemaInput): { min?: number; max?: number } {
        const schema = fieldSchemas[field];
        return typeof schema === 'object' ? { min: schema.minimum, max: schema.maximum } : {};
    }

    const queryClient = useQueryClient();
    const settingsQuery = createQuery(() => getSystemSettingsApiV1AdminSettingsGetOptions());

    let loaded = $derived(settingsQuery.data);
    // Edits go to a copy; structural sharing keeps the loaded settings across an unchanged refetch, so they survive it
    let settings = $derived.by(() => {
        const draft = $state<SystemSettingsSchemaInput>(structuredClone(loaded ?? {}));
        return draft;
    });

    function storeSettings(data: SystemSettingsSchemaOutput): void {
        queryClient.setQueryData(getSystemSettingsApiV1AdminSettingsGetQueryKey(), data);
    }

    const save = createMutation(() => ({
        ...updateSystemSettingsApiV1AdminSettingsPutMutation(),
        onSuccess: (data) => {
            storeSettings(data);
            toast.success('Settings saved successfully');
        },
    }));

    const reset = createMutation(() => ({
        ...resetSystemSettingsApiV1AdminSettingsResetPostMutation(),
        onSuccess: (data) => {
            storeSettings(data);
            toast.success('Settings reset to defaults');
        },
    }));

    function saveSettings(): void {
        const parsed = zSystemSettingsSchemaInput.safeParse(settings);
        if (!parsed.success) {
            toast.error(firstIssue(parsed.error));
            return;
        }
        save.mutate({ body: parsed.data });
    }

    function resetSettings(): void {
        if (!confirm('Are you sure you want to reset all settings to defaults?')) return;
        reset.mutate({});
    }
</script>

<div class="container mx-auto px-4 pb-8">
    <div class="flex justify-between items-center mb-6">
        <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">System Settings</h1>
    </div>

    <div class="card">
        <div class="p-6">
            <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">Configuration</h3>

            {#if settingsQuery.isPending}
                <div class="flex justify-center items-center h-64">
                    <Spinner size="xlarge" />
                </div>
            {:else}
                <div class="space-y-6">
                    <!-- Execution Limits -->
                    <div>
                        <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">
                            Execution Limits
                        </h4>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label
                                    for="max-timeout"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('max_timeout_seconds')}</label
                                >
                                <input
                                    id="max-timeout"
                                    type="number"
                                    bind:value={settings.max_timeout_seconds}
                                    class="form-input-standard"
                                    {...bounds('max_timeout_seconds')}
                                />
                            </div>
                            <div>
                                <label
                                    for="memory-limit"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('memory_limit')}</label
                                >
                                <input
                                    id="memory-limit"
                                    type="text"
                                    bind:value={settings.memory_limit}
                                    class="form-input-standard"
                                    placeholder={DEFAULTS.memory_limit}
                                />
                            </div>
                            <div>
                                <label
                                    for="cpu-limit"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('cpu_limit')}</label
                                >
                                <input
                                    id="cpu-limit"
                                    type="text"
                                    bind:value={settings.cpu_limit}
                                    class="form-input-standard"
                                    placeholder={DEFAULTS.cpu_limit}
                                />
                            </div>
                            <div>
                                <label
                                    for="max-concurrent"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('max_concurrent_executions')}</label
                                >
                                <input
                                    id="max-concurrent"
                                    type="number"
                                    bind:value={settings.max_concurrent_executions}
                                    class="form-input-standard"
                                    {...bounds('max_concurrent_executions')}
                                />
                            </div>
                            <div>
                                <label
                                    for="max-per-user"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('max_executions_per_user')}</label
                                >
                                <input
                                    id="max-per-user"
                                    type="number"
                                    bind:value={settings.max_executions_per_user}
                                    class="form-input-standard"
                                    {...bounds('max_executions_per_user')}
                                />
                            </div>
                        </div>
                    </div>

                    <!-- Security Settings -->
                    <div>
                        <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">
                            Security Settings
                        </h4>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label
                                    for="min-password"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('password_min_length')}</label
                                >
                                <input
                                    id="min-password"
                                    type="number"
                                    bind:value={settings.password_min_length}
                                    class="form-input-standard"
                                    {...bounds('password_min_length')}
                                />
                            </div>
                            <div>
                                <label
                                    for="session-timeout"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('session_timeout_minutes')}</label
                                >
                                <input
                                    id="session-timeout"
                                    type="number"
                                    bind:value={settings.session_timeout_minutes}
                                    class="form-input-standard"
                                    {...bounds('session_timeout_minutes')}
                                />
                            </div>
                            <div>
                                <label
                                    for="max-login"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('max_login_attempts')}</label
                                >
                                <input
                                    id="max-login"
                                    type="number"
                                    bind:value={settings.max_login_attempts}
                                    class="form-input-standard"
                                    {...bounds('max_login_attempts')}
                                />
                            </div>
                            <div>
                                <label
                                    for="lockout-duration"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('lockout_duration_minutes')}</label
                                >
                                <input
                                    id="lockout-duration"
                                    type="number"
                                    bind:value={settings.lockout_duration_minutes}
                                    class="form-input-standard"
                                    {...bounds('lockout_duration_minutes')}
                                />
                            </div>
                        </div>
                    </div>

                    <!-- Monitoring Settings -->
                    <div>
                        <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">
                            Monitoring Settings
                        </h4>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <div>
                                <label
                                    for="metrics-retention"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('metrics_retention_days')}</label
                                >
                                <input
                                    id="metrics-retention"
                                    type="number"
                                    bind:value={settings.metrics_retention_days}
                                    class="form-input-standard"
                                    {...bounds('metrics_retention_days')}
                                />
                            </div>
                            <div>
                                <label
                                    for="log-level"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('log_level')}</label
                                >
                                <select id="log-level" bind:value={settings.log_level} class="form-select-standard">
                                    {#each Object.values(LogLevel) as level (level)}
                                        <option value={level}>{level}</option>
                                    {/each}
                                </select>
                            </div>
                            <div>
                                <label
                                    for="enable-tracing"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('enable_tracing')}</label
                                >
                                <select
                                    id="enable-tracing"
                                    bind:value={settings.enable_tracing}
                                    class="form-select-standard"
                                >
                                    <option value={true}>{formatBoolean(true)}</option>
                                    <option value={false}>{formatBoolean(false)}</option>
                                </select>
                            </div>
                            <div>
                                <label
                                    for="sampling-rate"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >{fieldTitle('sampling_rate')}</label
                                >
                                <input
                                    id="sampling-rate"
                                    type="number"
                                    bind:value={settings.sampling_rate}
                                    class="form-input-standard"
                                    {...bounds('sampling_rate')}
                                    step="0.1"
                                />
                            </div>
                        </div>
                    </div>

                    <!-- Actions -->
                    <div
                        class="flex justify-end gap-3 pt-4 border-t border-border-default dark:border-dark-border-default"
                    >
                        <button
                            type="button"
                            onclick={resetSettings}
                            class="btn btn-ghost"
                            disabled={save.isPending || reset.isPending}
                        >
                            {reset.isPending ? 'Resetting...' : 'Reset to Defaults'}
                        </button>
                        <button
                            type="button"
                            onclick={saveSettings}
                            class="btn btn-primary"
                            disabled={save.isPending || reset.isPending}
                        >
                            {save.isPending ? 'Saving...' : 'Save Settings'}
                        </button>
                    </div>
                </div>
            {/if}
        </div>
    </div>
</div>
