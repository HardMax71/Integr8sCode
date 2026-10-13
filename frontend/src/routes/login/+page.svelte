<script lang="ts">
    import { match, resolve } from '$app/paths';
    import { goto } from '$app/navigation';
    import { page } from '$app/state';
    import { createMutation } from '@tanstack/svelte-query';
    import * as z from 'zod/mini';
    import { Control, Field, FieldErrors, Label } from 'formsnap';
    import { loginApiV1AuthLoginPostMutation, zBodyLoginApiV1AuthLoginPost } from '#lib/api/index.ts';
    import { apiForm, filled } from '#lib/forms.ts';
    import { fieldTitle } from '#lib/formatters.ts';
    import { toast } from 'svelte-sonner';
    import { fade, fly } from 'svelte/transition';
    import Spinner from '#components/Spinner.svelte';

    const login = createMutation(() => ({
        ...loginApiV1AuthLoginPostMutation(),
        meta: { inlineErrors: true },
        onSuccess: async () => {
            toast.success('Login successful! Welcome back.');
            // match() only knows this app's pages, so a crafted redirect can't send the user off-site
            const route = await match(page.url.searchParams.get('redirect') ?? resolve('/(auth)/editor'));
            // refreshAll reruns the root layout's load, which reads the new session
            await goto(resolve(route?.id ?? '/(auth)/editor'), { refreshAll: true });
        },
    }));

    let loading = $derived(login.isPending);
    const error = $derived(login.error?.detail);

    const { username, password } = zBodyLoginApiV1AuthLoginPost.shape;
    const form = apiForm(z.object({ username: filled(username), password: filled(password) }), {
        onSubmit: () => login.reset(),
        onUpdate: ({ form: submitted }) => {
            if (submitted.valid) login.mutate({ body: submitted.data });
        },
    });
    const { form: formData, constraints, enhance } = form;
</script>

{#snippet field(name: 'username' | 'password', type: string, autocomplete: HTMLInputElement['autocomplete'])}
    <Field {form} {name}>
        <Control id={name}>
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
        <FieldErrors class="mt-1" />
    </Field>
{/snippet}

<svelte:head>
    <title>Login - Integr8sCode</title>
    <meta
        name="description"
        content="Sign in to Integr8sCode to access your saved projects, code snippets, and personalized development environment"
    />
</svelte:head>

<div class="min-h-[60vh] flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8" in:fade>
    <div class="max-w-md w-full space-y-8">
        <div class="text-center">
            <h2 class="text-3xl font-bold">Sign in to your account</h2>
            <p class="mt-2 text-sm text-fg-muted">
                Or <a href={resolve('/register')} class="link font-medium">create a new account</a>
            </p>
        </div>

        <form method="post" use:enhance novalidate class="mt-8 space-y-6 bg-surface p-8 rounded-lg shadow-md border">
            <input type="hidden" name="remember" value="true" hidden />

            {#if error}
                <p
                    class="mt-0 text-sm text-danger text-center"
                    data-testid="error-message"
                    in:fly={{ y: -10, duration: 200 }}
                >
                    {error}
                </p>
            {/if}

            <div class="space-y-2">
                {@render field('username', 'text', 'username')}
                {@render field('password', 'password', 'current-password')}
            </div>

            <div>
                <button type="submit" disabled={loading} class="btn btn-primary w-full">
                    {#if loading}
                        <span class="absolute left-0 inset-y-0 flex items-center pl-3">
                            <Spinner size="small" className="text-info" />
                        </span>
                        Logging in...
                    {:else}
                        Sign in
                    {/if}
                </button>
            </div>
        </form>
    </div>
</div>
