<script lang="ts">
  import { goto, route } from "@mateothegreat/svelte5-router";
  import { login } from "$stores/auth";
  import { addToast } from "$stores/toastStore";
  import { fade, fly } from "svelte/transition";
  import Spinner from '$components/Spinner.svelte';
  import { onMount } from 'svelte';
  import { updateMetaTags, pageMeta } from '$utils/meta';
  import { loadUserSettings } from '$lib/user-settings';

  let username = $state("");
  let password = $state("");
  let loading = $state(false);
  let error = $state<string | null>(null);
  
  onMount(() => {
    updateMetaTags(pageMeta.login.title, pageMeta.login.description);
    
    // Check for authentication message from redirect
    const authMessage = sessionStorage.getItem('authMessage');
    if (authMessage) {
      addToast(authMessage, "info");
      sessionStorage.removeItem('authMessage');
    }
  });

  async function handleLogin() {
    loading = true;
    error = null; // Clear previous error
    try {
      await login(username, password);

      // Load user settings in background (non-blocking)
      loadUserSettings().catch(err => console.warn('Failed to load user settings:', err));

      addToast("Login successful! Welcome back.", "success");

      // Check if there's a saved redirect path
      const redirectPath = sessionStorage.getItem('redirectAfterLogin');
      if (redirectPath) {
        sessionStorage.removeItem('redirectAfterLogin');
        goto(redirectPath);
      } else {
        goto("/editor"); // Default redirect to editor
      }
    } catch (err) {
      error = err.message || "Login failed. Please check your credentials.";
      addToast(error, "error");
    } finally {
      loading = false;
    }
  }
</script>

<div class="min-h-[60vh] flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8" in:fade>
  <div class="max-w-md w-full space-y-8">
    <div class="text-center">
      <h2 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">
        Sign in to your account
      </h2>
      <p class="mt-2 text-sm text-fg-muted dark:text-dark-fg-muted">
        Or <a href="/register" use:route class="font-medium text-primary-dark hover:text-primary dark:text-primary-light dark:hover:text-primary">create a new account</a>
      </p>
    </div>

    <form class="mt-8 space-y-6 bg-bg-alt dark:bg-dark-bg-alt p-8 rounded-lg shadow-md border border-border-default dark:border-dark-border-default" onsubmit={(e) => { e.preventDefault(); handleLogin(); }}>
      <input type="hidden" name="remember" value="true" hidden>

      {#if error}
        <p class="mt-0 text-sm text-red-600 dark:text-red-400 text-center" in:fly={{y: -10, duration: 200}}>{error}</p>
      {/if}

      <div class="space-y-2">
        <div>
          <label for="username" class="sr-only">Username</label>
          <input class="form-input-standard" bind:value={username} id="username" name="username" type="text" autocomplete="username" required
                 placeholder="Username">
        </div>
        <div>
          <label for="password" class="sr-only">Password</label>
          <input class="form-input-standard" bind:value={password} id="password" name="password" type="password" autocomplete="current-password" required
                 placeholder="Password">
        </div>
      </div>

      <div>
        <button type="submit" disabled={loading}
                class="btn btn-primary w-full flex justify-center items-center">
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
