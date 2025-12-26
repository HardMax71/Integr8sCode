<script lang="ts">
    import { onMount } from 'svelte';
    import {
        getSystemSettingsApiV1AdminSettingsGet,
        updateSystemSettingsApiV1AdminSettingsPut,
        resetSystemSettingsApiV1AdminSettingsResetPost,
    } from '$lib/api';
    import { addToast } from '$stores/toastStore';
    import AdminLayout from '$routes/admin/AdminLayout.svelte';
    import Spinner from '$components/Spinner.svelte';

    let settings = $state<{
        execution_limits: Record<string, unknown>;
        security_settings: Record<string, unknown>;
        monitoring_settings: Record<string, unknown>;
    }>({
        execution_limits: {},
        security_settings: {},
        monitoring_settings: {}
    });
    let loading = $state(false);
    let saving = $state(false);
    let resetting = $state(false);

    onMount(() => {
        loadSettings();
    });

    async function loadSettings(): Promise<void> {
        loading = true;
        try {
            const { data, error } = await getSystemSettingsApiV1AdminSettingsGet({});
            if (error) throw error;
            settings = data;
        } catch (err) {
            console.error('Failed to load settings:', err);
            const msg = (err as Error)?.message || 'Unknown error';
            addToast(`Failed to load settings: ${msg}`, 'error');
        } finally {
            loading = false;
        }
    }

    async function saveSettings(): Promise<void> {
        saving = true;
        try {
            const { error } = await updateSystemSettingsApiV1AdminSettingsPut({ body: settings });
            if (error) throw error;
            addToast('Settings saved successfully', 'success');
        } catch (err) {
            const msg = (err as Error)?.message || 'Unknown error';
            addToast(`Failed to save settings: ${msg}`, 'error');
        } finally {
            saving = false;
        }
    }

    async function resetSettings(): Promise<void> {
        if (!confirm('Are you sure you want to reset all settings to defaults?')) {
            return;
        }

        resetting = true;
        try {
            const { data, error } = await resetSystemSettingsApiV1AdminSettingsResetPost({});
            if (error) throw error;
            settings = data;
            addToast('Settings reset to defaults', 'success');
        } catch (err) {
            const msg = (err as Error)?.message || 'Unknown error';
            addToast(`Failed to reset settings: ${msg}`, 'error');
        } finally {
            resetting = false;
        }
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
                                    <input id="max-timeout" type="number" bind:value={settings.execution_limits.max_timeout_seconds}
                                        class="form-input-standard" min="10" max="600"/>
                                </div>
                                <div>
                                    <label for="max-memory" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max Memory (MB)</label>
                                    <input id="max-memory" type="number" bind:value={settings.execution_limits.max_memory_mb}
                                        class="form-input-standard" min="128" max="2048"/>
                                </div>
                                <div>
                                    <label for="max-cpu" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max CPU Cores</label>
                                    <input id="max-cpu" type="number" bind:value={settings.execution_limits.max_cpu_cores}
                                        class="form-input-standard" min="0.5" max="4" step="0.5"/>
                                </div>
                                <div>
                                    <label for="max-concurrent" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max Concurrent Executions</label>
                                    <input id="max-concurrent" type="number" bind:value={settings.execution_limits.max_concurrent_executions}
                                        class="form-input-standard" min="1" max="50"/>
                                </div>
                            </div>
                        </div>

                        <!-- Security Settings -->
                        <div>
                            <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">Security Settings</h4>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label for="min-password" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Min Password Length</label>
                                    <input id="min-password" type="number" bind:value={settings.security_settings.password_min_length}
                                        class="form-input-standard" min="6" max="32"/>
                                </div>
                                <div>
                                    <label for="session-timeout" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Session Timeout (minutes)</label>
                                    <input id="session-timeout" type="number" bind:value={settings.security_settings.session_timeout_minutes}
                                        class="form-input-standard" min="5" max="1440"/>
                                </div>
                                <div>
                                    <label for="max-login" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max Login Attempts</label>
                                    <input id="max-login" type="number" bind:value={settings.security_settings.max_login_attempts}
                                        class="form-input-standard" min="3" max="10"/>
                                </div>
                                <div>
                                    <label for="lockout-duration" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Lockout Duration (minutes)</label>
                                    <input id="lockout-duration" type="number" bind:value={settings.security_settings.lockout_duration_minutes}
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
                                    <input id="metrics-retention" type="number" bind:value={settings.monitoring_settings.metrics_retention_days}
                                        class="form-input-standard" min="1" max="90"/>
                                </div>
                                <div>
                                    <label for="log-level" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Log Level</label>
                                    <select id="log-level" bind:value={settings.monitoring_settings.log_level} class="form-select-standard">
                                        <option value="DEBUG">DEBUG</option>
                                        <option value="INFO">INFO</option>
                                        <option value="WARNING">WARNING</option>
                                        <option value="ERROR">ERROR</option>
                                    </select>
                                </div>
                                <div>
                                    <label for="enable-tracing" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Enable Tracing</label>
                                    <select id="enable-tracing" bind:value={settings.monitoring_settings.enable_tracing} class="form-select-standard">
                                        <option value={true}>Enabled</option>
                                        <option value={false}>Disabled</option>
                                    </select>
                                </div>
                                <div>
                                    <label for="sampling-rate" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Sampling Rate</label>
                                    <input id="sampling-rate" type="number" bind:value={settings.monitoring_settings.sampling_rate}
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