<script lang="ts">
    import { untrack } from 'svelte';
    import { Plus, X } from '@lucide/svelte';
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import { Control, ElementField, Field, FieldErrors, Label } from 'formsnap';
    import {
        getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGetOptions,
        getUserRateLimitsApiV1AdminRateLimitsUserIdGetOptions,
        getUserRateLimitsApiV1AdminRateLimitsUserIdGetQueryKey,
        listUsersApiV1AdminUsersGetQueryKey,
        resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPostMutation,
        updateUserRateLimitsApiV1AdminRateLimitsUserIdPutMutation,
        EndpointGroup,
        RateLimitAlgorithm,
        zRateLimitRuleRequest,
        zRateLimitUpdateRequest,
        type UserResponse,
    } from '#lib/api/index.ts';
    import { getGroupColor } from '#lib/admin/rate-limits/index.ts';
    import { apiForm } from '#lib/forms.ts';
    import { fieldTitle } from '#lib/formatters.ts';
    import Modal from '#components/Modal.svelte';
    import Spinner from '#components/Spinner.svelte';

    interface Props {
        user: UserResponse;
        onClose: () => void;
    }

    let { user, onClose }: Props = $props();

    const DEFAULT_MULTIPLIER = zRateLimitUpdateRequest.parse({}).global_multiplier;

    const queryClient = useQueryClient();
    // The page mounts the dialog per open and clears the user when it closes, so keep the id it opened with
    const path = { user_id: untrack(() => user.user_id) };
    const defaults = createQuery(() => getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGetOptions());
    const limits = createQuery(() => getUserRateLimitsApiV1AdminRateLimitsUserIdGetOptions({ path }));
    const refreshLimits = () =>
        queryClient.invalidateQueries({ queryKey: getUserRateLimitsApiV1AdminRateLimitsUserIdGetQueryKey({ path }) });

    let defaultRules = $derived(defaults.data ?? []);

    const save = createMutation(() => ({
        ...updateUserRateLimitsApiV1AdminRateLimitsUserIdPutMutation(),
        onSuccess: () => {
            onClose();
            return Promise.all([
                queryClient.invalidateQueries({ queryKey: listUsersApiV1AdminUsersGetQueryKey() }),
                refreshLimits(),
            ]);
        },
    }));
    const reset = createMutation(() => ({
        ...resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPostMutation(),
        onSuccess: refreshLimits,
    }));

    const form = apiForm(zRateLimitUpdateRequest, {
        onUpdate: ({ form: submitted }) => {
            if (submitted.valid) save.mutate({ path, body: submitted.data });
        },
    });
    const { form: formData, constraints, enhance } = form;

    // Loading or refreshing the limits starts the form over from them
    $effect(() => {
        if (!limits.data) return;
        const { bypass_rate_limit, global_multiplier, rules, notes } = limits.data.rate_limit_config;
        form.reset({ newState: { bypass_rate_limit, global_multiplier, rules, notes } });
    });

    let multiplied = $derived($formData.global_multiplier !== DEFAULT_MULTIPLIER);

    function effectiveRequests(requests: number): number {
        return Math.floor(requests * $formData.global_multiplier);
    }

    function addRule(): void {
        $formData.rules = [...$formData.rules, zRateLimitRuleRequest.parse({})];
    }

    function removeRule(index: number): void {
        $formData.rules = $formData.rules.filter((_, i) => i !== index);
    }
</script>

{#snippet errors()}
    <FieldErrors class="mt-1 text-xs text-danger" />
{/snippet}

<Modal open title="Rate Limits for {user.username}" {onClose} size="xl">
    {#if limits.isPending}
        <div class="flex justify-center py-8"><Spinner /></div>
    {:else}
        <form id="rate-limits-form" method="post" use:enhance novalidate class="space-y-4">
            <div class="border border-border rounded-lg p-4 bg-muted">
                <div class="flex items-center justify-between mb-3">
                    <h4 class="font-semibold text-fg">Quick Settings</h4>
                    <Field {form} name="bypass_rate_limit">
                        <Control>
                            {#snippet children({ props })}
                                <div class="flex items-center gap-2">
                                    <input
                                        {...props}
                                        type="checkbox"
                                        bind:checked={$formData.bypass_rate_limit}
                                        class="rounded"
                                    />
                                    <Label class="text-sm font-medium text-fg">{fieldTitle('bypass_rate_limit')}</Label>
                                </div>
                            {/snippet}
                        </Control>
                    </Field>
                </div>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <Field {form} name="global_multiplier">
                        <Control>
                            {#snippet children({ props })}
                                <div>
                                    <Label class="block text-sm font-medium mb-1 text-fg"
                                        >{fieldTitle('global_multiplier')}</Label
                                    >
                                    <input
                                        {...props}
                                        {...$constraints.global_multiplier}
                                        type="number"
                                        step="0.1"
                                        bind:value={$formData.global_multiplier}
                                        class="input w-full"
                                        disabled={$formData.bypass_rate_limit}
                                    />
                                    <p class="text-xs text-fg-muted mt-1">
                                        Multiplies all limits; {DEFAULT_MULTIPLIER} keeps them as they are
                                    </p>
                                    {@render errors()}
                                </div>
                            {/snippet}
                        </Control>
                    </Field>
                    <Field {form} name="notes">
                        <Control>
                            {#snippet children({ props })}
                                <div>
                                    <Label class="block text-sm font-medium mb-1 text-fg">{fieldTitle('notes')}</Label>
                                    <textarea
                                        {...props}
                                        bind:value={$formData.notes}
                                        rows="2"
                                        class="input w-full text-sm"></textarea>
                                </div>
                            {/snippet}
                        </Control>
                    </Field>
                </div>
            </div>

            <div class="border border-border rounded-lg p-4">
                <div class="flex justify-between items-center mb-4">
                    <h4 class="font-semibold text-fg">Endpoint Rate Limits</h4>
                    <button
                        type="button"
                        onclick={addRule}
                        class="btn btn-sm btn-primary flex items-center gap-1"
                        disabled={$formData.bypass_rate_limit}
                    >
                        <Plus class="w-4 h-4" />Add Rule
                    </button>
                </div>
                <div class="mb-4">
                    <h5 class="text-xs sm:text-sm font-medium text-fg-muted mb-2">Default Global Rules</h5>
                    <div class="space-y-2">
                        {#each defaultRules as rule (rule.endpoint_pattern)}
                            <div class="flex items-center justify-between p-3 bg-muted rounded-lg">
                                <div class="flex-1 grid grid-cols-2 lg:grid-cols-5 gap-2 lg:gap-4 items-center">
                                    <div>
                                        <span class="text-xs text-fg-muted">{fieldTitle('endpoint_pattern')}</span>
                                        <p class="text-sm font-mono text-fg">
                                            {rule.endpoint_pattern}
                                        </p>
                                    </div>
                                    <div>
                                        <span class="text-xs text-fg-muted">{fieldTitle('requests')}</span>
                                        <p class="text-sm text-fg">
                                            {#if multiplied}
                                                <span class="line-through text-fg-subtle">{rule.requests}</span>
                                                <span class="font-semibold text-info"
                                                    >{effectiveRequests(rule.requests)}</span
                                                >
                                            {:else}
                                                {rule.requests}
                                            {/if}
                                        </p>
                                    </div>
                                    <div>
                                        <span class="text-xs text-fg-muted">{fieldTitle('window_seconds')}</span>
                                        <p class="text-sm text-fg">
                                            {rule.window_seconds}
                                        </p>
                                    </div>
                                    <div>
                                        <span class="text-xs text-fg-muted">{fieldTitle('group')}</span>
                                        <span
                                            class="inline-block px-2 py-1 text-xs rounded-full {getGroupColor(
                                                rule.group,
                                            )}">{rule.group}</span
                                        >
                                    </div>
                                    <div>
                                        <span class="text-xs text-fg-muted">{fieldTitle('algorithm')}</span>
                                        <p class="text-sm text-fg">
                                            {rule.algorithm}
                                        </p>
                                    </div>
                                </div>
                            </div>
                        {/each}
                    </div>
                </div>

                {#if $formData.rules.length > 0}
                    <div>
                        <h5 class="text-xs sm:text-sm font-medium text-fg-muted mb-2">
                            {fieldTitle('rules')}
                        </h5>
                        <div class="space-y-2">
                            {#each $formData.rules as rule, index (index)}
                                <div class="p-3 bg-info-soft border border-info/30 rounded-lg">
                                    <div class="flex flex-col lg:flex-row items-start lg:items-center gap-3">
                                        <ElementField {form} name="rules[{index}].endpoint_pattern">
                                            <Control>
                                                {#snippet children({ props })}
                                                    <div class="w-full lg:flex-1 lg:min-w-[200px]">
                                                        <input
                                                            {...props}
                                                            type="text"
                                                            bind:value={rule.endpoint_pattern}
                                                            aria-label={fieldTitle('endpoint_pattern')}
                                                            class="input input-sm w-full"
                                                            disabled={$formData.bypass_rate_limit}
                                                        />
                                                        {@render errors()}
                                                    </div>
                                                {/snippet}
                                            </Control>
                                        </ElementField>
                                        <div class="flex items-center gap-1 flex-wrap">
                                            <ElementField {form} name="rules[{index}].requests">
                                                <Control>
                                                    {#snippet children({ props })}
                                                        <input
                                                            {...props}
                                                            {...$constraints.rules?.requests}
                                                            type="number"
                                                            bind:value={rule.requests}
                                                            aria-label={fieldTitle('requests')}
                                                            class="input input-sm w-16"
                                                            disabled={$formData.bypass_rate_limit}
                                                        />
                                                    {/snippet}
                                                </Control>
                                                {@render errors()}
                                            </ElementField>
                                            <span class="text-xs text-fg-muted">/</span>
                                            <ElementField {form} name="rules[{index}].window_seconds">
                                                <Control>
                                                    {#snippet children({ props })}
                                                        <input
                                                            {...props}
                                                            {...$constraints.rules?.window_seconds}
                                                            type="number"
                                                            bind:value={rule.window_seconds}
                                                            aria-label={fieldTitle('window_seconds')}
                                                            class="input input-sm w-16"
                                                            disabled={$formData.bypass_rate_limit}
                                                        />
                                                    {/snippet}
                                                </Control>
                                                {@render errors()}
                                            </ElementField>
                                            <span class="text-xs text-fg-muted">s</span>
                                            {#if multiplied}
                                                <span class="text-xs text-info ml-2">
                                                    (effective {effectiveRequests(
                                                        rule.requests,
                                                    )}/{rule.window_seconds}s)
                                                </span>
                                            {/if}
                                        </div>
                                        <ElementField {form} name="rules[{index}].group">
                                            <Control>
                                                {#snippet children({ props })}
                                                    <select
                                                        {...props}
                                                        bind:value={rule.group}
                                                        aria-label={fieldTitle('group')}
                                                        class="input input-sm"
                                                        disabled={$formData.bypass_rate_limit}
                                                    >
                                                        {#each Object.values(EndpointGroup) as group (group)}
                                                            <option value={group}>{group}</option>
                                                        {/each}
                                                    </select>
                                                {/snippet}
                                            </Control>
                                        </ElementField>
                                        <ElementField {form} name="rules[{index}].algorithm">
                                            <Control>
                                                {#snippet children({ props })}
                                                    <select
                                                        {...props}
                                                        bind:value={rule.algorithm}
                                                        aria-label={fieldTitle('algorithm')}
                                                        class="input input-sm"
                                                        disabled={$formData.bypass_rate_limit}
                                                    >
                                                        {#each Object.values(RateLimitAlgorithm) as algorithm (algorithm)}
                                                            <option value={algorithm}>{algorithm}</option>
                                                        {/each}
                                                    </select>
                                                {/snippet}
                                            </Control>
                                        </ElementField>
                                        <ElementField {form} name="rules[{index}].enabled">
                                            <Control>
                                                {#snippet children({ props })}
                                                    <div class="flex items-center gap-2">
                                                        <input
                                                            {...props}
                                                            type="checkbox"
                                                            bind:checked={rule.enabled}
                                                            class="rounded text-info"
                                                            disabled={$formData.bypass_rate_limit}
                                                        />
                                                        <Label class="text-xs font-medium cursor-pointer"
                                                            >{fieldTitle('enabled')}</Label
                                                        >
                                                    </div>
                                                {/snippet}
                                            </Control>
                                        </ElementField>
                                        <button
                                            type="button"
                                            onclick={() => removeRule(index)}
                                            class="text-danger hover:text-danger p-1"
                                            disabled={$formData.bypass_rate_limit}
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
            {#if limits.data && Object.keys(limits.data.current_usage).length > 0}
                <div class="border border-border rounded-lg p-4">
                    <div class="flex justify-between items-center mb-3">
                        <h4 class="font-semibold text-fg">
                            {fieldTitle('current_usage')}
                        </h4>
                        <button type="button" onclick={() => reset.mutate({ path })} class="btn btn-sm btn-secondary"
                            >Reset All Counters</button
                        >
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                        {#each Object.entries(limits.data.current_usage) as [endpoint, usageData] (endpoint)}
                            <div class="flex justify-between items-center p-2 bg-muted rounded">
                                <span class="text-sm font-mono text-fg-muted">{endpoint}</span>
                                <div class="flex items-center gap-2">
                                    <span class="text-xs text-fg-muted">{usageData.algorithm}</span>
                                    <span class="text-xs text-fg-muted">{fieldTitle('remaining')}</span>
                                    <span class="text-sm font-semibold text-fg">
                                        {usageData.remaining}
                                    </span>
                                </div>
                            </div>
                        {/each}
                    </div>
                </div>
            {/if}
        </form>
        <div class="flex gap-3 justify-end mt-6">
            <button type="button" onclick={onClose} class="btn btn-secondary" disabled={save.isPending}>Cancel</button>
            <button
                type="submit"
                form="rate-limits-form"
                class="btn btn-primary flex items-center gap-2"
                disabled={save.isPending}
            >
                {#if save.isPending}
                    <Spinner size="small" />Saving...
                {:else}
                    Save Changes
                {/if}
            </button>
        </div>
    {/if}
</Modal>
