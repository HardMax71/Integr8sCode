<script>
    import { onMount } from 'svelte';
    import { api } from '../../lib/api';
    import { addNotification } from '../../stores/notifications';
    import AdminLayout from './AdminLayout.svelte';
    
    let settings = {
        rate_limits: {},
        kafka_settings: {},
        execution_limits: {},
        security_settings: {},
        monitoring_settings: {}
    };
    let loading = false;
    let saving = false;
    let resetting = false;
    
    onMount(() => {
        loadSettings();
    });
    
    async function loadSettings() {
        loading = true;
        try {
            settings = await api.get('/api/v1/admin/settings/');
        } catch (error) {
            console.error('Failed to load settings:', error);
            addNotification(`Failed to load settings: ${error.message}`, 'error');
        } finally {
            loading = false;
        }
    }
    
    async function saveSettings() {
        saving = true;
        try {
            await api.put('/api/v1/admin/settings/', settings);
            addNotification('Settings saved successfully', 'success');
        } catch (error) {
            addNotification(`Failed to save settings: ${error.message}`, 'error');
        } finally {
            saving = false;
        }
    }
    
    async function resetSettings() {
        if (!confirm('Are you sure you want to reset all settings to defaults?')) {
            return;
        }
        
        resetting = true;
        try {
            settings = await api.post('/api/v1/admin/settings/reset', {});
            addNotification('Settings reset to defaults', 'success');
        } catch (error) {
            addNotification(`Failed to reset settings: ${error.message}`, 'error');
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
                        <svg class="animate-spin h-12 w-12 text-primary" fill="none" viewBox="0 0 24 24">
                            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                    </div>
                {:else}
                    <div class="space-y-6">
                        <!-- Rate Limits -->
                        <div>
                            <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">Rate Limits</h4>
                            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Default</label>
                                    <input type="text" bind:value={settings.rate_limits.default} 
                                        class="form-input-standard" placeholder="100/minute"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Auth Endpoints</label>
                                    <input type="text" bind:value={settings.rate_limits.auth} 
                                        class="form-input-standard" placeholder="5/minute"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Execution</label>
                                    <input type="text" bind:value={settings.rate_limits.execution} 
                                        class="form-input-standard" placeholder="20/minute"/>
                                </div>
                            </div>
                        </div>

                        <!-- Kafka Settings -->
                        <div>
                            <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">Kafka Settings</h4>
                            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Retention Days</label>
                                    <input type="number" bind:value={settings.kafka_settings.retention_days} 
                                        class="form-input-standard" min="1" max="30"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Partition Count</label>
                                    <input type="number" bind:value={settings.kafka_settings.partition_count} 
                                        class="form-input-standard" min="1" max="10"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Replication Factor</label>
                                    <input type="number" bind:value={settings.kafka_settings.replication_factor} 
                                        class="form-input-standard" min="1" max="3"/>
                                </div>
                            </div>
                        </div>

                        <!-- Execution Limits -->
                        <div>
                            <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">Execution Limits</h4>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max Timeout (seconds)</label>
                                    <input type="number" bind:value={settings.execution_limits.max_timeout_seconds} 
                                        class="form-input-standard" min="10" max="600"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max Memory (MB)</label>
                                    <input type="number" bind:value={settings.execution_limits.max_memory_mb} 
                                        class="form-input-standard" min="128" max="2048"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max CPU Cores</label>
                                    <input type="number" bind:value={settings.execution_limits.max_cpu_cores} 
                                        class="form-input-standard" min="0.5" max="4" step="0.5"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max Concurrent Executions</label>
                                    <input type="number" bind:value={settings.execution_limits.max_concurrent_executions} 
                                        class="form-input-standard" min="1" max="50"/>
                                </div>
                            </div>
                        </div>

                        <!-- Security Settings -->
                        <div>
                            <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">Security Settings</h4>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Min Password Length</label>
                                    <input type="number" bind:value={settings.security_settings.password_min_length} 
                                        class="form-input-standard" min="6" max="32"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Session Timeout (minutes)</label>
                                    <input type="number" bind:value={settings.security_settings.session_timeout_minutes} 
                                        class="form-input-standard" min="5" max="1440"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Max Login Attempts</label>
                                    <input type="number" bind:value={settings.security_settings.max_login_attempts} 
                                        class="form-input-standard" min="3" max="10"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Lockout Duration (minutes)</label>
                                    <input type="number" bind:value={settings.security_settings.lockout_duration_minutes} 
                                        class="form-input-standard" min="5" max="60"/>
                                </div>
                            </div>
                        </div>

                        <!-- Monitoring Settings -->
                        <div>
                            <h4 class="text-md font-semibold text-fg-default dark:text-dark-fg-default mb-3">Monitoring Settings</h4>
                            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Metrics Retention Days</label>
                                    <input type="number" bind:value={settings.monitoring_settings.metrics_retention_days} 
                                        class="form-input-standard" min="1" max="90"/>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Log Level</label>
                                    <select bind:value={settings.monitoring_settings.log_level} class="form-input-standard">
                                        <option value="DEBUG">DEBUG</option>
                                        <option value="INFO">INFO</option>
                                        <option value="WARNING">WARNING</option>
                                        <option value="ERROR">ERROR</option>
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Enable Tracing</label>
                                    <select bind:value={settings.monitoring_settings.enable_tracing} class="form-input-standard">
                                        <option value={true}>Enabled</option>
                                        <option value={false}>Disabled</option>
                                    </select>
                                </div>
                                <div>
                                    <label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Sampling Rate</label>
                                    <input type="number" bind:value={settings.monitoring_settings.sampling_rate} 
                                        class="form-input-standard" min="0" max="1" step="0.1"/>
                                </div>
                            </div>
                        </div>

                        <!-- Actions -->
                        <div class="flex justify-end gap-3 pt-4 border-t border-border-default dark:border-dark-border-default">
                            <button 
                                on:click={resetSettings}
                                class="btn btn-ghost"
                                disabled={saving || resetting}
                            >
                                {resetting ? 'Resetting...' : 'Reset to Defaults'}
                            </button>
                            <button 
                                on:click={saveSettings}
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