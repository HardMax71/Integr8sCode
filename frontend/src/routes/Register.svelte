<script lang="ts">
    import { goto, route } from "@mateothegreat/svelte5-router";
    import { toast } from 'svelte-sonner';
    import { fade, fly } from "svelte/transition";
    import { registerApiV1AuthRegisterPost } from "$lib/api";
    import { onMount } from 'svelte';
    import { updateMetaTags, pageMeta } from '$utils/meta';
    import Spinner from '$components/Spinner.svelte';

    let username = $state("");
    let email = $state("");
    let password = $state("");
    let confirmPassword = $state("");
    let loading = $state(false);
    let error = $state<string | null>(null);
    
    onMount(() => {
        updateMetaTags(pageMeta.register.title, pageMeta.register.description);
    });

    async function handleRegister() {
        if (password !== confirmPassword) {
            error = "Passwords do not match.";
            toast.error(error);
            return;
        }
        if (password.length < 8) { // Backend requires min 8 characters
            error = "Password must be at least 8 characters long.";
            toast.warning(error);
            return;
        }

        loading = true;
        error = null;
        try {
            const { error: apiError } = await registerApiV1AuthRegisterPost({ body: { username, email, password } });
            if (apiError) throw apiError;
            toast.success("Registration successful! Please log in.");
            goto("/login");
        } catch (err: unknown) {
            const errObj = err as { detail?: string; message?: string } | null;
            error = errObj?.detail || errObj?.message || "Registration failed. Please try again.";
            toast.error(error);
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
        Or <a href="/login" use:route class="font-medium text-primary-dark hover:text-primary dark:text-primary-light dark:hover:text-primary">sign in to your existing account</a>
      </p>
    </div>

    <form class="mt-8 space-y-6 bg-bg-alt dark:bg-dark-bg-alt p-8 rounded-lg shadow-md border border-border-default dark:border-dark-border-default" onsubmit={(e) => { e.preventDefault(); handleRegister(); }}>
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
                class="btn btn-primary w-full flex justify-center items-center">
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
