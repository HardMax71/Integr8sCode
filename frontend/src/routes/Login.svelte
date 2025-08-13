<script>
  import { navigate, Link } from "svelte-routing";
  import { login } from "../stores/auth.js";
  import { addNotification } from "../stores/notifications.js";
  import { fade, fly } from "svelte/transition";
  import Spinner from '../components/Spinner.svelte'; // Assuming Spinner component exists
  import { onMount } from 'svelte';
  import { updateMetaTags, pageMeta } from '../utils/meta.js';
  import { loadUserSettings } from '../lib/user-settings.js';

  let username = "";
  let password = "";
  let loading = false;
  let error = null;
  
  onMount(() => {
    updateMetaTags(pageMeta.login.title, pageMeta.login.description);
    
    // Check for authentication message from redirect
    const authMessage = sessionStorage.getItem('authMessage');
    if (authMessage) {
      addNotification(authMessage, "info");
      sessionStorage.removeItem('authMessage');
    }
  });

  async function handleLogin() {
    loading = true;
    error = null; // Clear previous error
    try {
      await login(username, password);
      
      // Load and apply user settings (theme, etc)
      await loadUserSettings();
      
      addNotification("Login successful! Welcome back.", "success");
      
      // Check if there's a saved redirect path
      const redirectPath = sessionStorage.getItem('redirectAfterLogin');
      if (redirectPath) {
        sessionStorage.removeItem('redirectAfterLogin');
        navigate(redirectPath);
      } else {
        navigate("/editor"); // Default redirect to editor
      }
    } catch (err) {
      error = err.message || "Login failed. Please check your credentials.";
      addNotification(error, "error");
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
        Or <Link to="/register" class="font-medium text-primary-dark hover:text-primary dark:text-primary-light dark:hover:text-primary">create a new account</Link>
      </p>
    </div>

    <form class="mt-8 space-y-6 bg-bg-alt dark:bg-dark-bg-alt p-8 rounded-lg shadow-md border border-border-default dark:border-dark-border-default" on:submit|preventDefault={handleLogin}>
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
                class="group relative w-full flex justify-center py-2 px-4 border border-transparent text-sm font-medium rounded-md text-white bg-primary hover:bg-primary-dark focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary dark:focus:ring-offset-dark-bg-alt disabled:opacity-60">
          {#if loading}
            <span class="absolute left-0 inset-y-0 flex items-center pl-3">
                <svg class="h-5 w-5 text-blue-300 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
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
