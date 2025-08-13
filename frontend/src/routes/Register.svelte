<script>
    import { navigate, Link } from "svelte-routing";
    import { addNotification } from "../stores/notifications.js";
    import { fade, fly } from "svelte/transition";
    import { api } from "../lib/api.js";
    import { onMount } from 'svelte';
    import { updateMetaTags, pageMeta } from '../utils/meta.js';
    // import { backendUrl } from "../config.js"; // Use relative path for proxy

    let username = "";
    let email = "";
    let password = "";
    let confirmPassword = "";
    let loading = false;
    let error = null;
    
    onMount(() => {
        updateMetaTags(pageMeta.register.title, pageMeta.register.description);
    });

    async function handleRegister() {
        if (password !== confirmPassword) {
            error = "Passwords do not match.";
            addNotification(error, "error");
            return;
        }
        if (password.length < 8) { // Backend requires min 8 characters
            error = "Password must be at least 8 characters long.";
            addNotification(error, "warning");
            return;
        }

        loading = true;
        error = null;
        try {
            // Use api module instead of axios for consistency
            await api.post(`/api/v1/auth/register`, { username, email, password });
            addNotification("Registration successful! Please log in.", "success");
            navigate("/login"); // Redirect to login page
        } catch (err) {
            error = err.response?.data?.detail || err.message || "Registration failed. Please try again.";
            addNotification(error, "error");
            console.error("Registration error:", err);
        } finally {
            loading = false;
        }
    }
</script>

<div class="min-h-[60vh] flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8" in:fade>
  <div class="max-w-md w-full space-y-8">
    <div class="text-center">
      <h2 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">
        Create a new account
      </h2>
      <p class="mt-2 text-sm text-fg-muted dark:text-dark-fg-muted">
        Or <Link to="/login" class="font-medium text-primary-dark hover:text-primary dark:text-primary-light dark:hover:text-primary">sign in to your existing account</Link>
      </p>
    </div>

    <form class="mt-8 space-y-6 bg-bg-alt dark:bg-dark-bg-alt p-8 rounded-lg shadow-md border border-border-default dark:border-dark-border-default" on:submit|preventDefault={handleRegister}>
      {#if error}
        <p class="mt-0 text-sm text-red-600 dark:text-red-400 text-center" in:fly={{y: -10, duration: 200}}>{error}</p>
      {/if}

      <div class="space-y-2">
        <div>
          <label for="username" class="sr-only">Username</label>
          <input bind:value={username} id="username" name="username" type="text" required
                 class="form-input-standard"
                 placeholder="Username">
        </div>
         <div>
          <label for="email" class="sr-only">Email address</label>
          <input bind:value={email} id="email" name="email" type="email" autocomplete="email" required
                 class="form-input-standard"
                 placeholder="Email address">
        </div>
        <div>
          <label for="password" class="sr-only">Password</label>
          <input bind:value={password} id="password" name="password" type="password" autocomplete="new-password" required
                 class="form-input-standard"
                 placeholder="Password (min. 8 characters)">
        </div>
         <div>
          <label for="confirm-password" class="sr-only">Confirm Password</label>
          <input bind:value={confirmPassword} id="confirm-password" name="confirm-password" type="password" autocomplete="new-password" required
                 class="form-input-standard"
                 placeholder="Confirm Password">
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
            Registering...
          {:else}
            Create Account
          {/if}
        </button>
      </div>
    </form>
  </div>
</div>
