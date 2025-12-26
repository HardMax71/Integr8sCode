<script lang="ts">
    import { onDestroy } from 'svelte';
    import { toasts, removeToast, TOAST_DURATION, type Toast, type ToastType } from "$stores/toastStore";
    import { fly } from "svelte/transition";
    import { CircleCheck, CircleX, AlertTriangle, Info, X } from '@lucide/svelte';

    let timers: Record<string, ReturnType<typeof setInterval>> = {};

    // Subscribe to toasts and start timers for new ones
    let toastList = $state<Toast[]>([]);
    const unsubscribeToasts = toasts.subscribe(value => {
        toastList = value;
        if (typeof window !== 'undefined') {
            value.forEach(toast => {
                if (!toast.timerStarted && !timers[toast.id]) {
                    startTimer(toast);
                }
            });
        }
    });

    function startTimer(toast: Toast) {
        if (!toast || timers[toast.id]) return;

        const start = Date.now();
        if (toast.progress === undefined || toast.progress <= 0) {
            toast.progress = 1;
        }

        const intervalId = setInterval(() => {
            const elapsed = Date.now() - start;
            const currentDuration = TOAST_DURATION * (toast.progress ?? 1);
            const progress = Math.max(0, (currentDuration - elapsed) / TOAST_DURATION);

            toast.progress = progress;
            toasts.update(n => n);

            if (progress <= 0) {
                clearTimer(toast);
                removeToast(toast.id);
            }
        }, 50);

        timers[toast.id] = intervalId;
        toast.timerStarted = true;
    }

    function clearTimer(toast: Toast) {
        if (toast && timers[toast.id]) {
            clearInterval(timers[toast.id]);
            delete timers[toast.id];
        }
    }

    onDestroy(() => {
        unsubscribeToasts();
        Object.values(timers).forEach(clearInterval);
        timers = {};
    });

    function getToastClasses(type: ToastType): string {
        const base = "toast-item";
        switch (type) {
            case 'success':
                return `${base} bg-green-50 border-green-200 text-green-800 dark:bg-green-950 dark:border-green-800 dark:text-green-200`;
            case 'error':
                return `${base} bg-red-50 border-red-200 text-red-800 dark:bg-red-950 dark:border-red-800 dark:text-red-200`;
            case 'warning':
                return `${base} bg-yellow-50 border-yellow-200 text-yellow-800 dark:bg-yellow-950 dark:border-yellow-800 dark:text-yellow-200`;
            case 'info':
            default:
                return `${base} bg-blue-50 border-blue-200 text-blue-800 dark:bg-blue-950 dark:border-blue-800 dark:text-blue-200`;
        }
    }

    function getIconClasses(type: ToastType): string {
        const base = "shrink-0 mr-3 pt-0.5";
        switch (type) {
            case 'success': return `${base} text-green-400`;
            case 'error':   return `${base} text-red-400`;
            case 'warning': return `${base} text-yellow-400`;
            case 'info':
            default:        return `${base} text-blue-400`;
        }
    }

    function getButtonClasses(type: ToastType): string {
        const base = "ml-3 -mr-1 -my-1 p-1 rounded-md focus:outline-hidden focus:ring-2 focus:ring-offset-2 dark:focus:ring-offset-dark-bg-alt opacity-70 hover:opacity-100 transition-opacity";
        switch (type) {
            case 'success': return `${base} focus:ring-green-500 focus:ring-offset-green-50 dark:focus:ring-offset-green-950`;
            case 'error':   return `${base} focus:ring-red-500 focus:ring-offset-red-50 dark:focus:ring-offset-red-950`;
            case 'warning': return `${base} focus:ring-yellow-500 focus:ring-offset-yellow-50 dark:focus:ring-offset-yellow-950`;
            case 'info':
            default:        return `${base} focus:ring-blue-500 focus:ring-offset-blue-50 dark:focus:ring-offset-blue-950`;
        }
    }

    function getTimerClasses(type: ToastType): string {
        const base = "toast-timer";
        switch (type) {
            case 'success': return `${base} bg-green-300 dark:bg-green-600`;
            case 'error':   return `${base} bg-red-300 dark:bg-red-600`;
            case 'warning': return `${base} bg-yellow-300 dark:bg-yellow-600`;
            case 'info':
            default:        return `${base} bg-blue-300 dark:bg-blue-600`;
        }
    }
</script>

<div class="toast-container">
    {#each toastList as toast (toast.id)}
        <div
             role="alert"
             class={getToastClasses(toast.type)}
             in:fly={{ x: 100, duration: 300, easing: (t) => 1 - Math.pow(1 - t, 3) }}
             out:fly={{ x: 100, opacity: 0, duration: 200, easing: (t) => t * t }}
             onmouseenter={() => clearTimer(toast)}
             onmouseleave={() => startTimer(toast)}
        >
            <div class={getIconClasses(toast.type)}>
               {#if toast.type === 'success'} <CircleCheck class="w-5 h-5" />
               {:else if toast.type === 'error'} <CircleX class="w-5 h-5" />
               {:else if toast.type === 'warning'} <AlertTriangle class="w-5 h-5" />
               {:else} <Info class="w-5 h-5" /> {/if}
            </div>

            <div class="flex-grow text-sm font-medium">
                {toast.message}
            </div>

            <button
                    class={getButtonClasses(toast.type)}
                    onclick={() => { clearTimer(toast); removeToast(toast.id); }}
                    aria-label="Close toast"
            >
                <X class="h-4 w-4" />
            </button>

            {#if toast.progress > 0}
                <div
                        class={getTimerClasses(toast.type)}
                        style="transform: scaleX({toast.progress || 0});"
                ></div>
            {/if}
        </div>
    {/each}
</div>