<script lang="ts">
    import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
    import { Control, Field, FieldErrors, Label } from 'formsnap';
    import {
        getSystemSettingsApiV1AdminSettingsGetOptions,
        getSystemSettingsApiV1AdminSettingsGetQueryKey,
        updateSystemSettingsApiV1AdminSettingsPutMutation,
        resetSystemSettingsApiV1AdminSettingsResetPostMutation,
        type SystemSettingsSchemaInput,
        type SystemSettingsSchemaOutput,
        zSystemSettingsSchemaInput,
    } from '#lib/api/index.ts';
    import { apiForm } from '#lib/forms.ts';
    import { fieldTitle } from '#lib/formatters.ts';
    import { toast } from 'svelte-sonner';
    import Spinner from '#components/Spinner.svelte';

    const queryClient = useQueryClient();
    const settingsQuery = createQuery(() => getSystemSettingsApiV1AdminSettingsGetOptions());

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

    const busy = $derived(save.isPending || reset.isPending);

    const form = apiForm(zSystemSettingsSchemaInput, {
        onUpdate: ({ form: submitted }) => {
            if (submitted.valid) save.mutate({ body: submitted.data });
        },
    });
    const { form: formData, constraints, enhance } = form;

    // Loading, saving and resetting put new settings in the query, and the form starts over from them
    $effect(() => {
        if (settingsQuery.data) form.reset({ newState: settingsQuery.data });
    });

    function resetSettings(): void {
        if (!confirm('Are you sure you want to reset all settings to defaults?')) return;
        reset.mutate({});
    }
</script>

{#snippet setting(name: keyof SystemSettingsSchemaInput, type: 'number' | 'text' = 'number')}
    <Field {form} {name}>
        <Control>
            {#snippet children({ props })}
                <div class="field">
                    <Label>{fieldTitle(name)}</Label>
                    <input
                        {...props}
                        {...$constraints[name]}
                        {type}
                        bind:value={$formData[name]}
                        class="form-input-standard"
                    />
                    <FieldErrors class="mt-1" />
                </div>
            {/snippet}
        </Control>
    </Field>
{/snippet}

<div class="container mx-auto px-4 pb-8">
    <div class="flex justify-between items-center mb-6">
        <h1 class="text-3xl">System Settings</h1>
    </div>

    <div class="card">
        <div class="p-6">
            <h3 class="text-lg font-semibold mb-4">Configuration</h3>

            {#if settingsQuery.isPending}
                <div class="flex justify-center items-center h-64">
                    <Spinner size="xlarge" />
                </div>
            {:else}
                <form method="post" use:enhance novalidate class="space-y-6">
                    <div>
                        <h4 class="font-semibold mb-3">Execution Limits</h4>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {@render setting('max_timeout_seconds')}
                            {@render setting('memory_limit', 'text')}
                            {@render setting('cpu_limit', 'text')}
                            {@render setting('max_concurrent_executions')}
                            {@render setting('max_executions_per_user')}
                        </div>
                    </div>

                    <div>
                        <h4 class="font-semibold mb-3">Security Settings</h4>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {@render setting('password_min_length')}
                            {@render setting('session_timeout_minutes')}
                            {@render setting('max_login_attempts')}
                            {@render setting('lockout_duration_minutes')}
                        </div>
                    </div>

                    <div class="flex justify-end gap-3 pt-4 border-t">
                        <button type="button" onclick={resetSettings} class="btn btn-ghost" disabled={busy}>
                            {reset.isPending ? 'Resetting...' : 'Reset to Defaults'}
                        </button>
                        <button type="submit" class="btn btn-primary" disabled={busy}>
                            {save.isPending ? 'Saving...' : 'Save Settings'}
                        </button>
                    </div>
                </form>
            {/if}
        </div>
    </div>
</div>
