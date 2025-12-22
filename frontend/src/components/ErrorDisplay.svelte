<script lang="ts">
  let { error, title = 'Application Error', showDetails = true }: {
    error: Error | string;
    title?: string;
    showDetails?: boolean;
  } = $props();

  const errorMessage = $derived(error instanceof Error ? error.message : String(error));
  const errorStack = $derived(error instanceof Error ? error.stack : null);

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
        <svg class="h-8 w-8 text-red-600 dark:text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      </div>
    </div>

    <!-- Title -->
    <h1 class="text-xl sm:text-2xl font-bold text-center text-fg-default dark:text-dark-fg-default mb-2">
      {title}
    </h1>

    <!-- Error Message -->
    <p class="text-center text-red-600 dark:text-red-400 mb-6">
      {errorMessage}
    </p>

    <!-- Stack Trace (collapsible) -->
    {#if showDetails && errorStack}
      <details class="mb-6">
        <summary class="cursor-pointer text-sm text-fg-muted dark:text-dark-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default transition-colors">
          Show technical details
        </summary>
        <pre class="mt-2 p-3 bg-code-bg rounded-lg text-xs text-gray-300 overflow-x-auto max-h-48 overflow-y-auto font-mono">{errorStack}</pre>
      </details>
    {/if}

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
        class="flex-1 btn py-2.5 text-sm font-medium bg-bg-default dark:bg-dark-bg-default border border-border-default dark:border-dark-border-default text-fg-default dark:text-dark-fg-default hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
      >
        Go to Home
      </button>
    </div>

    <!-- Help Text -->
    <p class="mt-6 text-xs text-center text-fg-muted dark:text-dark-fg-muted">
      If this problem persists, please check the browser console for more details.
    </p>
  </div>
</div>
