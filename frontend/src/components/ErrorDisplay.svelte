<script lang="ts">
    import { TriangleAlert } from '@lucide/svelte';

    let {
        error,
        title = 'Application Error',
    }: {
        error: Error | string;
        title?: string;
    } = $props();

    // Determine if this is a network/connection error for user-friendly messaging
    const isNetworkError = $derived.by(() => {
        const msg = error instanceof Error ? error.message : String(error);
        return (
            msg.toLowerCase().includes('network') ||
            msg.toLowerCase().includes('fetch') ||
            msg.toLowerCase().includes('connection')
        );
    });

    // User-friendly message - never expose raw error details
    const userMessage = $derived(
        isNetworkError
            ? 'Unable to connect to the server. Please check your internet connection and try again.'
            : 'Something went wrong. Our team has been notified and is working on it.',
    );

    function reload() {
        window.location.reload();
    }

    function goHome() {
        window.location.href = '/';
    }
</script>

<div class="min-h-dvh flex items-center justify-center p-4">
    <div class="max-w-lg w-full bg-surface rounded-xl border border-danger/30 shadow-lg p-6 sm:p-8">
        <div class="flex justify-center mb-6">
            <div class="size-16 rounded-full bg-danger-soft flex items-center justify-center">
                <TriangleAlert class="size-8 text-danger" />
            </div>
        </div>

        <h1 class="text-xl sm:text-2xl text-center mb-2">
            {title}
        </h1>

        <p class="text-center text-fg-muted mb-6">
            {userMessage}
        </p>

        <div class="flex flex-col sm:flex-row gap-3">
            <button type="button" onclick={reload} class="flex-1 btn btn-primary py-2.5 text-sm font-medium">
                Reload Page
            </button>
            <button
                type="button"
                onclick={goHome}
                class="flex-1 btn py-2.5 text-sm font-medium bg-page border hover:bg-muted transition-colors"
            >
                Go to Home
            </button>
        </div>

        <p class="mt-6 text-xs text-center text-fg-muted">If this problem persists, please contact support.</p>
    </div>
</div>
