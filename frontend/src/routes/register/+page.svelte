<script lang="ts">
    import { resolve } from '$app/paths';
    import { goto } from '$app/navigation';
    import { toast } from 'svelte-sonner';
    import { fade, fly } from 'svelte/transition';
    import * as z from 'zod/mini';
    import { createMutation } from '@tanstack/svelte-query';
    import { Control, Field, FieldErrors, Label } from 'formsnap';
    import { registerApiV1AuthRegisterPostMutation, zUserCreate } from '#lib/api/index.ts';
    import { apiForm, filled } from '#lib/forms.ts';
    import { fieldTitle } from '#lib/formatters.ts';
    import { getErrorMessage } from '#lib/api-interceptors.ts';
    import Spinner from '#components/Spinner.svelte';

    const zRegister = z
        .extend(z.pick(zUserCreate, { email: true, password: true }), {
            username: filled(zUserCreate.shape.username),
            confirm_password: z.string(),
        })
        .check(
            z.refine((v) => v.password === v.confirm_password, {
                message: 'Passwords do not match',
                path: ['confirm_password'],
            }),
        );

    const register = createMutation(() => ({
        ...registerApiV1AuthRegisterPostMutation(),
        meta: { inlineErrors: true },
        onSuccess: () => {
            toast.success('Registration successful! Please log in.');
            void goto(resolve('/login'));
        },
    }));

    const form = apiForm(zRegister, {
        onSubmit: () => register.reset(),
        onUpdate: ({ form: submitted }) => {
            if (!submitted.valid) return;
            const { username, email, password } = submitted.data;
            register.mutate({ body: { username, email, password } });
        },
    });
    const { form: formData, constraints, enhance } = form;

    let loading = $derived(register.isPending);
    let error = $derived(
        register.error ? getErrorMessage(register.error, 'Registration failed. Please try again.') : null,
    );
</script>

{#snippet field(
    name: 'username' | 'email' | 'password' | 'confirm_password',
    id: string,
    type: string,
    autocomplete: HTMLInputElement['autocomplete'],
)}
    <Field {form} {name}>
        <Control {id}>
            {#snippet children({ props })}
                <Label class="sr-only">{fieldTitle(name)}</Label>
                <input
                    {...props}
                    {...$constraints[name]}
                    {type}
                    {autocomplete}
                    placeholder={fieldTitle(name)}
                    bind:value={$formData[name]}
                    class="form-input-standard"
                />
            {/snippet}
        </Control>
        <FieldErrors class="mt-1 text-sm text-red-600 dark:text-red-400" />
    </Field>
{/snippet}

<svelte:head>
    <title>Register - Integr8sCode</title>
    <meta
        name="description"
        content="Create a free Integr8sCode account to save your projects, collaborate with others, and access advanced coding features"
    />
</svelte:head>

<div class="min-h-[60vh] flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8" in:fade>
    <div class="max-w-md w-full space-y-8">
        <div class="text-center">
            <h2 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">Create a new account</h2>
            <p class="mt-2 text-sm text-fg-muted dark:text-dark-fg-muted">
                Or <a
                    href={resolve('/login')}
                    class="font-medium text-primary-dark hover:text-primary dark:text-primary-light dark:hover:text-primary"
                    >sign in to your existing account</a
                >
            </p>
        </div>

        <form
            method="post"
            use:enhance
            novalidate
            class="mt-8 space-y-6 bg-bg-alt dark:bg-dark-bg-alt p-8 rounded-lg shadow-md border border-border-default dark:border-dark-border-default"
        >
            {#if error}
                <p
                    class="mt-0 text-sm text-red-600 dark:text-red-400 text-center"
                    data-testid="error-message"
                    in:fly={{ y: -10, duration: 200 }}
                >
                    {error}
                </p>
            {/if}

            <div class="space-y-2">
                {@render field('username', 'username', 'text', 'username')}
                {@render field('email', 'email', 'email', 'email')}
                {@render field('password', 'password', 'password', 'new-password')}
                {@render field('confirm_password', 'confirm-password', 'password', 'new-password')}
            </div>
            <div>
                <button
                    type="submit"
                    disabled={loading}
                    class="btn btn-primary w-full flex justify-center items-center"
                >
                    {#if loading}
                        <span class="absolute left-0 inset-y-0 flex items-center pl-3">
                            <Spinner size="small" className="text-blue-300" />
                        </span>
                        Registering...
                    {:else}
                        Create Account
                    {/if}
                </button>
            </div>
        </form>
    </div>
</div>
