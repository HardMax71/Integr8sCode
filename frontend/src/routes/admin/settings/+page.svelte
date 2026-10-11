<script lang="ts">
    import { onMount } from 'svelte';
    import {
        getSystemSettingsApiV1AdminSettingsGet,
        updateSystemSettingsApiV1AdminSettingsPut,
        resetSystemSettingsApiV1AdminSettingsResetPost,
        LogLevel,
        type SystemSettingsSchemaInput,
        zSystemSettingsSchemaInput,
    } from '#lib/api/index.ts';
    import { firstIssue } from '#lib/validation.ts';
    import * as z from 'zod/mini';
    import { toast } from 'svelte-sonner';
    import Spinner from '#components/Spinner.svelte';

    let settings = $state<SystemSettingsSchemaInput>({});

    const fieldSchemas = z.toJSONSchema(zSystemSettingsSchemaInput, { io: 'input' }).properties ?? {};

    // min and max for a numeric input, taken from the API's validation rules
    function bounds(field: keyof SystemSettingsSchemaInput): { min?: number; max?: number } {
        const schema = fieldSchemas[field];
        return typeof schema === 'object' ? { min: schema.minimum, max: schema.maximum } : {};
    }
    let loading = $state(false);
    let saving = $state(false);
    let resetting = $state(false);

    onMount(() => {
        loadSettings();
    });

    async function loadSettings(): Promise<void> {
        loading = true;
        const { data, error } = await getSystemSettingsApiV1AdminSettingsGet({});
        if (error) {
            loading = false;
            return;
        }
        if (data) settings = data;
        loading = false;
    }

    async function saveSettings(): Promise<void> {
        const parsed = zSystemSettingsSchemaInput.safeParse(settings);
        if (!parsed.success) {
            toast.error(firstIssue(parsed.error));
            return;
        }
        saving = true;
        const { error } = await updateSystemSettingsApiV1AdminSettingsPut({ body: parsed.data });
        if (error) {
            saving = false;
            return;
        }
        toast.success('Settings saved successfully');
        saving = false;
    }

    async function resetSettings(): Promise<void> {
        if (!confirm('Are you sure you want to reset all settings to defaults?')) {
            return;
        }

        resetting = true;
        const { data, error } = await resetSystemSettingsApiV1AdminSettingsResetPost({});
        if (error) {
            resetting = false;
            return;
        }
        if (data) settings = data;
        toast.success('Settings reset to defaults');
        resetting = false;
    }
</script>

<div class="container mx-auto px-4 pb-8">
    <div class="flex justify-between items-center mb-6">
        <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">System Settings</h1>
    </div>

    <div class="card">
        <div class="p-6">
            <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">Configuration</h3>

            {#if loading}
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
                                    >Max Timeout (seconds)</label
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
                                    >Memory Limit (e.g. 512Mi)</label
                                >
                                <input
                                    id="memory-limit"
                                    type="text"
                                    bind:value={settings.memory_limit}
                                    class="form-input-standard"
                                    placeholder="512Mi"
                                />
                            </div>
                            <div>
                                <label
                                    for="cpu-limit"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >CPU Limit (e.g. 2000m)</label
                                >
                                <input
                                    id="cpu-limit"
                                    type="text"
                                    bind:value={settings.cpu_limit}
                                    class="form-input-standard"
                                    placeholder="2000m"
                                />
                            </div>
                            <div>
                                <label
                                    for="max-concurrent"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >Max Concurrent Executions</label
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
                                    >Max Executions per User</label
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
                                    >Min Password Length</label
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
                                    >Session Timeout (minutes)</label
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
                                    >Max Login Attempts</label
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
                                    >Lockout Duration (minutes)</label
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
                                    >Metrics Retention Days</label
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
                                    >Log Level</label
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
                                    >Enable Tracing</label
                                >
                                <select
                                    id="enable-tracing"
                                    bind:value={settings.enable_tracing}
                                    class="form-select-standard"
                                >
                                    <option value={true}>Enabled</option>
                                    <option value={false}>Disabled</option>
                                </select>
                            </div>
                            <div>
                                <label
                                    for="sampling-rate"
                                    class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                    >Sampling Rate</label
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
                            disabled={saving || resetting}
                        >
                            {resetting ? 'Resetting...' : 'Reset to Defaults'}
                        </button>
                        <button
                            type="button"
                            onclick={saveSettings}
                            class="btn btn-primary"
                            disabled={saving || resetting}
                        >
                            {saving ? 'Saving...' : 'Save Settings'}
                        </button>
                    </div>
                </div>
            {/if}
        </div>
    </div>
</div>
