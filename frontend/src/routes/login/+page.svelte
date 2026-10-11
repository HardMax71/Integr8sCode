<script lang="ts">
    import { goto } from '$app/navigation';
    import { createMutation } from '@tanstack/svelte-query';
    import { loginApiV1AuthLoginPostMutation } from '#lib/api/index.ts';
    import { authStore } from '#stores/auth.svelte.ts';
    import { toast } from 'svelte-sonner';
    import { fade, fly } from 'svelte/transition';
    import Spinner from '#components/Spinner.svelte';
    import { onMount } from 'svelte';
    import { getErrorMessage } from '#lib/api-interceptors.ts';

    let username = $state('');
    let password = $state('');

    const login = createMutation(() => ({
        ...loginApiV1AuthLoginPostMutation(),
        meta: { inlineErrors: true },
        onSuccess: async (data) => {
            await authStore.startSession(data);
            toast.success('Login successful! Welcome back.');

            // Only a local path, so a crafted link can't send the user off-site
            const redirectPath = sessionStorage.getItem('redirectAfterLogin');
            sessionStorage.removeItem('redirectAfterLogin');
            if (redirectPath && redirectPath.startsWith('/') && !redirectPath.startsWith('//')) {
                void goto(redirectPath);
            } else {
                void goto('/editor');
            }
        },
    }));

    let loading = $derived(login.isPending);
    let error = $derived(
        login.error ? getErrorMessage(login.error, 'Login failed. Please check your credentials.') : null,
    );

    onMount(() => {
        // Check for authentication message from redirect
        const authMessage = sessionStorage.getItem('authMessage');
        if (authMessage) {
            toast.info(authMessage);
            sessionStorage.removeItem('authMessage');
        }
    });

    function handleLogin() {
        login.mutate({ body: { username, password, scope: '' } });
    }
</script>

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
            <h2 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">Sign in to your account</h2>
            <p class="mt-2 text-sm text-fg-muted dark:text-dark-fg-muted">
                Or <a
                    href="/register"
                    class="font-medium text-primary-dark hover:text-primary dark:text-primary-light dark:hover:text-primary"
                    >create a new account</a
                >
            </p>
        </div>

        <form
            class="mt-8 space-y-6 bg-bg-alt dark:bg-dark-bg-alt p-8 rounded-lg shadow-md border border-border-default dark:border-dark-border-default"
            onsubmit={(e) => {
                e.preventDefault();
                handleLogin();
            }}
        >
            <input type="hidden" name="remember" value="true" hidden />

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
                <div>
                    <label for="username" class="sr-only">Username</label>
                    <input
                        class="form-input-standard"
                        bind:value={username}
                        id="username"
                        name="username"
                        type="text"
                        autocomplete="username"
                        required
                        placeholder="Username"
                    />
                </div>
                <div>
                    <label for="password" class="sr-only">Password</label>
                    <input
                        class="form-input-standard"
                        bind:value={password}
                        id="password"
                        name="password"
                        type="password"
                        autocomplete="current-password"
                        required
                        placeholder="Password"
                    />
                </div>
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
                        Logging in...
                    {:else}
                        Sign in
                    {/if}
                </button>
            </div>
        </form>
    </div>
</div>
