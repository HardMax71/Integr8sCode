<script lang="ts">
  import { AlertTriangle } from '@lucide/svelte';

  let { error, title = 'Application Error' }: {
    error: Error | string;
    title?: string;
  } = $props();

  // Determine if this is a network/connection error for user-friendly messaging
  const isNetworkError = $derived.by(() => {
    const msg = error instanceof Error ? error.message : String(error);
    return msg.toLowerCase().includes('network') ||
           msg.toLowerCase().includes('fetch') ||
           msg.toLowerCase().includes('connection');
  });

  // User-friendly message - never expose raw error details
  const userMessage = $derived(
    isNetworkError
      ? 'Unable to connect to the server. Please check your internet connection and try again.'
      : 'Something went wrong. Our team has been notified and is working on it.'
  );

  function reload() {
    window.location.reload();
  }

  function goHome() {
    window.location.href = '/';
  }
</script>

<div class="min-h-screen bg-bg-default dark:bg-dark-bg-default flex items-center justify-center p-4">
  <div class="max-w-lg w-full bg-bg-alt dark:bg-dark-bg-alt rounded-xl border border-red-200 dark:border-red-900/50 shadow-lg p-6 sm:p-8">
    <!-- Error Icon -->
    <div class="flex justify-center mb-6">
      <div class="h-16 w-16 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
        <AlertTriangle class="h-8 w-8 text-red-600 dark:text-red-400" />
      </div>
    </div>

    <!-- Title -->
    <h1 class="text-xl sm:text-2xl font-bold text-center text-fg-default dark:text-dark-fg-default mb-2">
      {title}
    </h1>

    <!-- User-friendly Error Message -->
    <p class="text-center text-fg-muted dark:text-dark-fg-muted mb-6">
      {userMessage}
    </p>

    <!-- Actions -->
    <div class="flex flex-col sm:flex-row gap-3">
      <button
        onclick={reload}
        class="flex-1 btn btn-primary py-2.5 text-sm font-medium"
      >
        Reload Page
      </button>
      <button
        onclick={goHome}
        class="flex-1 btn py-2.5 text-sm font-medium bg-bg-default dark:bg-dark-bg-default border border-border-default dark:border-dark-border-default text-fg-default dark:text-dark-fg-default hover:bg-interactive-hover dark:hover:bg-dark-interactive-hover transition-colors"
      >
        Go to Home
      </button>
    </div>

    <!-- Help Text -->
    <p class="mt-6 text-xs text-center text-fg-muted dark:text-dark-fg-muted">
      If this problem persists, please contact support.
    </p>
  </div>
</div>
