<script lang="ts">
    import { onMount } from 'svelte';
    import {
        getSystemSettingsApiV1AdminSettingsGet,
        updateSystemSettingsApiV1AdminSettingsPut,
        resetSystemSettingsApiV1AdminSettingsResetPost,
        type SystemSettingsSchema,
    } from '$lib/api';
    import { toast } from 'svelte-sonner';
    import AdminLayout from '$routes/admin/AdminLayout.svelte';
    import Spinner from '$components/Spinner.svelte';

    let settings = $state<SystemSettingsSchema>({});
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
        saving = true;
        const { error } = await updateSystemSettingsApiV1AdminSettingsPut({ body: settings });
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

<AdminLayout path="/admin/settings">
    <div class="container mx-auto px-4 pb-8">
        <div class="flex justify-between items-center mb-6">
            <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">System Settings</h1>
        </div>

        <div class="card">
            <div class="p-6">
                <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">
                    Configuration
                </h3>

                {#if loading}
                    <div class="flex justify-center items-center h-64">
                        <Spinner size="xlarge" />
                    </div>
                {:else}
                    <div class="space-y-6">
                        <!-- Execution Limits -->
                        <div>
                            <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">Execution Limits</h4>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label for="max-timeout" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max Timeout (seconds)</label>
                                    <input id="max-timeout" type="number" bind:value={settings.max_timeout_seconds}
                                        class="form-input-standard" min="10" max="3600"/>
                                </div>
                                <div>
                                    <label for="memory-limit" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Memory Limit (e.g. 512Mi)</label>
                                    <input id="memory-limit" type="text" bind:value={settings.memory_limit}
                                        class="form-input-standard" placeholder="512Mi"/>
                                </div>
                                <div>
                                    <label for="cpu-limit" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">CPU Limit (e.g. 2000m)</label>
                                    <input id="cpu-limit" type="text" bind:value={settings.cpu_limit}
                                        class="form-input-standard" placeholder="2000m"/>
                                </div>
                                <div>
                                    <label for="max-concurrent" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max Concurrent Executions</label>
                                    <input id="max-concurrent" type="number" bind:value={settings.max_concurrent_executions}
                                        class="form-input-standard" min="1" max="100"/>
                                </div>
                            </div>
                        </div>

                        <!-- Security Settings -->
                        <div>
                            <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">Security Settings</h4>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label for="min-password" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Min Password Length</label>
                                    <input id="min-password" type="number" bind:value={settings.password_min_length}
                                        class="form-input-standard" min="4" max="32"/>
                                </div>
                                <div>
                                    <label for="session-timeout" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Session Timeout (minutes)</label>
                                    <input id="session-timeout" type="number" bind:value={settings.session_timeout_minutes}
                                        class="form-input-standard" min="5" max="1440"/>
                                </div>
                                <div>
                                    <label for="max-login" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max Login Attempts</label>
                                    <input id="max-login" type="number" bind:value={settings.max_login_attempts}
                                        class="form-input-standard" min="3" max="10"/>
                                </div>
                                <div>
                                    <label for="lockout-duration" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Lockout Duration (minutes)</label>
                                    <input id="lockout-duration" type="number" bind:value={settings.lockout_duration_minutes}
                                        class="form-input-standard" min="5" max="60"/>
                                </div>
                            </div>
                        </div>

                        <!-- Monitoring Settings -->
                        <div>
                            <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">Monitoring Settings</h4>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label for="metrics-retention" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Metrics Retention Days</label>
                                    <input id="metrics-retention" type="number" bind:value={settings.metrics_retention_days}
                                        class="form-input-standard" min="7" max="90"/>
                                </div>
                                <div>
                                    <label for="log-level" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Log Level</label>
                                    <select id="log-level" bind:value={settings.log_level} class="form-select-standard">
                                        <option value="DEBUG">DEBUG</option>
                                        <option value="INFO">INFO</option>
                                        <option value="WARNING">WARNING</option>
                                        <option value="ERROR">ERROR</option>
                                    </select>
                                </div>
                                <div>
                                    <label for="enable-tracing" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Enable Tracing</label>
                                    <select id="enable-tracing" bind:value={settings.enable_tracing} class="form-select-standard">
                                        <option value={true}>Enabled</option>
                                        <option value={false}>Disabled</option>
                                    </select>
                                </div>
                                <div>
                                    <label for="sampling-rate" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Sampling Rate</label>
                                    <input id="sampling-rate" type="number" bind:value={settings.sampling_rate}
                                        class="form-input-standard" min="0" max="1" step="0.1"/>
                                </div>
                            </div>
                        </div>

                        <!-- Actions -->
                        <div class="flex justify-end gap-3 pt-4 border-t border-border-default dark:border-dark-border-default">
                            <button
                                onclick={resetSettings}
                                class="btn btn-ghost"
                                disabled={saving || resetting}
                            >
                                {resetting ? 'Resetting...' : 'Reset to Defaults'}
                            </button>
                            <button
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
</AdminLayout>
