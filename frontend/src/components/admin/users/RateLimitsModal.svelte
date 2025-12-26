<script lang="ts">
    import { Plus, X } from '@lucide/svelte';
    import type { UserResponse, UserRateLimit, RateLimitRule } from '../../../lib/api';
    import {
        getGroupColor,
        getDefaultRulesWithMultiplier,
        detectGroupFromEndpoint,
        createEmptyRule
    } from '../../../lib/admin/users';
    import Modal from '../../Modal.svelte';
    import Spinner from '../../Spinner.svelte';

    interface Props {
        open: boolean;
        user: UserResponse | null;
        config: UserRateLimit | null;
        usage: Record<string, { count?: number; tokens_remaining?: number }> | null;
        loading: boolean;
        saving: boolean;
        onClose: () => void;
        onSave: () => void;
        onReset: () => void;
    }

    let {
        open,
        user,
        config = $bindable(null),
        usage,
        loading,
        saving,
        onClose,
        onSave,
        onReset
    }: Props = $props();

    let defaultRulesWithEffective = $derived(
        config ? getDefaultRulesWithMultiplier(config.global_multiplier) : []
    );

    function handleEndpointChange(rule: RateLimitRule): void {
        if (rule.endpoint_pattern) {
            rule.group = detectGroupFromEndpoint(rule.endpoint_pattern);
        }
    }

    function addNewRule(): void {
        if (!config) return;
        if (!config.rules) config.rules = [];
        config.rules = [...config.rules, createEmptyRule()];
    }

    function removeRule(index: number): void {
        if (!config?.rules) return;
        config.rules = config.rules.filter((_, i) => i !== index);
    }
</script>

<Modal {open} title="Rate Limits for {user?.username || ''}" {onClose} size="xl">
    {#snippet children()}
        {#if loading}
            <div class="flex justify-center py-8"><Spinner /></div>
        {:else if config}
            <div class="space-y-4">
                <!-- Quick Settings -->
                <div class="border border-neutral-200 dark:border-neutral-700 rounded-lg p-4 bg-neutral-50 dark:bg-neutral-900">
                    <div class="flex items-center justify-between mb-3">
                        <h4 class="font-semibold text-fg-default dark:text-dark-fg-default">Quick Settings</h4>
                        <label class="flex items-center gap-2">
                            <input type="checkbox" bind:checked={config.bypass_rate_limit} class="rounded" />
                            <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Bypass all rate limits</span>
                        </label>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label for="global-multiplier" class="block text-sm font-medium mb-1 text-fg-default dark:text-dark-fg-default">
                                Global Multiplier
                            </label>
                            <input
                                id="global-multiplier"
                                type="number"
                                bind:value={config.global_multiplier}
                                min="0.01"
                                step="0.1"
                                class="input w-full"
                                disabled={config.bypass_rate_limit}
                            />
                            <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1">
                                Multiplies all limits (1.0 = default, 2.0 = double)
                            </p>
                        </div>
                        <div>
                            <label for="admin-notes" class="block text-sm font-medium mb-1 text-fg-default dark:text-dark-fg-default">
                                Admin Notes
                            </label>
                            <textarea
                                id="admin-notes"
                                bind:value={config.notes}
                                rows="2"
                                class="input w-full text-sm"
                                placeholder="Notes about this user's rate limits..."
                            ></textarea>
                        </div>
                    </div>
                </div>

                <!-- Endpoint-Specific Limits -->
                <div class="border border-neutral-200 dark:border-neutral-700 rounded-lg p-4">
                    <div class="flex justify-between items-center mb-4">
                        <h4 class="font-semibold text-fg-default dark:text-dark-fg-default">Endpoint Rate Limits</h4>
                        <button
                            onclick={addNewRule}
                            class="btn btn-sm btn-primary flex items-center gap-1"
                            disabled={config.bypass_rate_limit}
                        >
                            <Plus class="w-4 h-4" />Add Rule
                        </button>
                    </div>

                    <!-- Default Rules -->
                    <div class="mb-4">
                        <h5 class="text-xs sm:text-sm font-medium text-neutral-600 dark:text-neutral-400 mb-2">Default Global Rules</h5>
                        <div class="space-y-2">
                            {#each defaultRulesWithEffective as rule}
                                <div class="flex items-center justify-between p-3 bg-neutral-50 dark:bg-neutral-900 rounded-lg">
                                    <div class="flex-1 grid grid-cols-2 lg:grid-cols-4 gap-2 lg:gap-4 items-center">
                                        <div>
                                            <span class="text-xs text-neutral-500 dark:text-neutral-400">Endpoint</span>
                                            <p class="text-sm font-mono text-fg-default dark:text-dark-fg-default">{rule.endpoint_pattern}</p>
                                        </div>
                                        <div>
                                            <span class="text-xs text-neutral-500 dark:text-neutral-400">Limit</span>
                                            <p class="text-sm text-fg-default dark:text-dark-fg-default">
                                                {#if config.global_multiplier !== 1.0}
                                                    <span class="line-through text-neutral-400">{rule.requests}</span>
                                                    <span class="font-semibold text-blue-600 dark:text-blue-400">{rule.effective_requests}</span>
                                                {:else}
                                                    {rule.requests}
                                                {/if}
                                                req / {rule.window_seconds}s
                                            </p>
                                        </div>
                                        <div>
                                            <span class="text-xs text-neutral-500 dark:text-neutral-400">Group</span>
                                            <span class="inline-block px-2 py-1 text-xs rounded-full {getGroupColor(rule.group)}">{rule.group}</span>
                                        </div>
                                        <div>
                                            <span class="text-xs text-neutral-500 dark:text-neutral-400">Algorithm</span>
                                            <p class="text-sm text-fg-default dark:text-dark-fg-default">{rule.algorithm}</p>
                                        </div>
                                    </div>
                                </div>
                            {/each}
                        </div>
                    </div>

                    <!-- User-Specific Rules -->
                    {#if config.rules && config.rules.length > 0}
                        <div>
                            <h5 class="text-xs sm:text-sm font-medium text-neutral-600 dark:text-neutral-400 mb-2">User-Specific Overrides</h5>
                            <div class="space-y-2">
                                {#each config.rules as rule, index}
                                    <div class="p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
                                        <div class="flex flex-col lg:flex-row items-start lg:items-center gap-3">
                                            <div class="w-full lg:flex-1 lg:min-w-[200px]">
                                                <input
                                                    type="text"
                                                    bind:value={rule.endpoint_pattern}
                                                    oninput={() => handleEndpointChange(rule)}
                                                    placeholder="Endpoint pattern"
                                                    class="input input-sm w-full"
                                                    disabled={config.bypass_rate_limit}
                                                />
                                            </div>
                                            <div class="flex items-center gap-1 flex-wrap">
                                                <input
                                                    type="number"
                                                    bind:value={rule.requests}
                                                    min="1"
                                                    class="input input-sm w-16"
                                                    disabled={config.bypass_rate_limit}
                                                />
                                                <span class="text-xs text-neutral-500">/</span>
                                                <input
                                                    type="number"
                                                    bind:value={rule.window_seconds}
                                                    min="1"
                                                    class="input input-sm w-16"
                                                    disabled={config.bypass_rate_limit}
                                                />
                                                <span class="text-xs text-neutral-500">s</span>
                                                {#if config.global_multiplier !== 1.0}
                                                    <span class="text-xs text-blue-600 dark:text-blue-400 ml-2">
                                                        (→ {Math.floor(rule.requests * config.global_multiplier)}/{rule.window_seconds}s)
                                                    </span>
                                                {/if}
                                            </div>
                                            <span class="inline-block px-2 py-1 text-xs rounded-full {getGroupColor(rule.group)}">{rule.group}</span>
                                            <select bind:value={rule.algorithm} class="input input-sm" disabled={config.bypass_rate_limit}>
                                                <option value="sliding_window">Sliding</option>
                                                <option value="token_bucket">Token</option>
                                                <option value="fixed_window">Fixed</option>
                                            </select>
                                            <label class="flex items-center gap-2 cursor-pointer">
                                                <input
                                                    type="checkbox"
                                                    bind:checked={rule.enabled}
                                                    class="rounded text-blue-600"
                                                    disabled={config.bypass_rate_limit}
                                                />
                                                <span class="text-xs font-medium">{rule.enabled ? 'Enabled' : 'Disabled'}</span>
                                            </label>
                                            <button
                                                onclick={() => removeRule(index)}
                                                class="text-red-600 hover:text-red-800 dark:text-red-400 p-1"
                                                disabled={config.bypass_rate_limit}
                                                title="Remove rule"
                                            >
                                                <X class="w-4 h-4" />
                                            </button>
                                        </div>
                                    </div>
                                {/each}
                            </div>
                        </div>
                    {/if}
                </div>

                <!-- Current Usage -->
                {#if usage && Object.keys(usage).length > 0}
                    <div class="border border-neutral-200 dark:border-neutral-700 rounded-lg p-4">
                        <div class="flex justify-between items-center mb-3">
                            <h4 class="font-semibold text-fg-default dark:text-dark-fg-default">Current Usage</h4>
                            <button onclick={onReset} class="btn btn-sm btn-secondary">Reset All Counters</button>
                        </div>
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {#each Object.entries(usage) as [endpoint, usageData]}
                                <div class="flex justify-between p-2 bg-neutral-50 dark:bg-neutral-900 rounded">
                                    <span class="text-sm font-mono text-fg-muted dark:text-dark-fg-muted">{endpoint}</span>
                                    <span class="text-sm font-semibold text-fg-default dark:text-dark-fg-default">
                                        {usageData.count || usageData.tokens_remaining || 0}
                                    </span>
                                </div>
                            {/each}
                        </div>
                    </div>
                {/if}
            </div>
            <div class="flex gap-3 justify-end mt-6">
                <button onclick={onClose} class="btn btn-secondary" disabled={saving}>Cancel</button>
                <button onclick={onSave} class="btn btn-primary flex items-center gap-2" disabled={saving || loading}>
                    {#if saving}
                        <Spinner size="small" />Saving...
                    {:else}
                        Save Changes
                    {/if}
                </button>
            </div>
        {/if}
    {/snippet}
</Modal>
