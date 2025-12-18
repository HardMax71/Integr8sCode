<script>
    import { onDestroy } from 'svelte';
    import { toasts, removeToast, TOAST_DURATION } from "../stores/toastStore.js";
    import { fly } from "svelte/transition";

    const checkCircleIcon = `<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" /></svg>`;
    const errorIcon = `<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" /></svg>`;
    const warningIcon = `<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" /></svg>`;
    const infoIcon = `<svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd" /></svg>`;
    const closeIcon = `<svg class="h-4 w-4" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" /></svg>`;

    let timers = {};

    function startTimer(toast) {
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

    function clearTimer(toast) {
        if (toast && timers[toast.id]) {
            clearInterval(timers[toast.id]);
            delete timers[toast.id];
        }
    }

    $: {
        if (typeof window !== 'undefined') {
            $toasts.forEach(toast => {
                if (!toast.timerStarted && !timers[toast.id]) {
                    startTimer(toast);
                }
            });
        }
    }

    onDestroy(() => {
        Object.values(timers).forEach(clearInterval);
        timers = {};
    });

    function getToastClasses(type) {
        let base = "toast";
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

    function getIconClasses(type) {
        let base = "shrink-0 mr-3 pt-0.5";
        switch (type) {
            case 'success': return `${base} text-green-400`;
            case 'error':   return `${base} text-red-400`;
            case 'warning': return `${base} text-yellow-400`;
            case 'info':
            default:        return `${base} text-blue-400`;
        }
    }

    function getButtonClasses(type) {
        let base = "ml-3 -mr-1 -my-1 p-1 rounded-md focus:outline-hidden focus:ring-2 focus:ring-offset-2 dark:focus:ring-offset-dark-bg-alt opacity-70 hover:opacity-100 transition-opacity";
        switch (type) {
            case 'success': return `${base} focus:ring-green-500 focus:ring-offset-green-50 dark:focus:ring-offset-green-950`;
            case 'error':   return `${base} focus:ring-red-500 focus:ring-offset-red-50 dark:focus:ring-offset-red-950`;
            case 'warning': return `${base} focus:ring-yellow-500 focus:ring-offset-yellow-50 dark:focus:ring-offset-yellow-950`;
            case 'info':
            default:        return `${base} focus:ring-blue-500 focus:ring-offset-blue-50 dark:focus:ring-offset-blue-950`;
        }
    }

    function getTimerClasses(type) {
        let base = "timer";
        switch (type) {
            case 'success': return `${base} bg-green-300 dark:bg-green-600`;
            case 'error':   return `${base} bg-red-300 dark:bg-red-600`;
            case 'warning': return `${base} bg-yellow-300 dark:bg-yellow-600`;
            case 'info':
            default:        return `${base} bg-blue-300 dark:bg-blue-600`;
        }
    }
</script>

<div class="toasts-container">
    {#each $toasts as toast (toast.id)}
        <div
             role="alert"
             class={getToastClasses(toast.type)}
             in:fly={{ x: 100, duration: 300, easing: (t) => 1 - Math.pow(1 - t, 3) }}
             out:fly={{ x: 100, opacity: 0, duration: 200, easing: (t) => t * t }}
             on:mouseenter={() => clearTimer(toast)}
             on:mouseleave={() => startTimer(toast)}
        >
            <div class={getIconClasses(toast.type)}>
               {#if toast.type === 'success'} {@html checkCircleIcon}
               {:else if toast.type === 'error'} {@html errorIcon}
               {:else if toast.type === 'warning'} {@html warningIcon}
               {:else} {@html infoIcon} {/if}
            </div>

            <div class="flex-grow text-sm font-medium">
                {toast.message}
            </div>

            <button
                    class={getButtonClasses(toast.type)}
                    on:click={() => { clearTimer(toast); removeToast(toast.id); }}
                    aria-label="Close toast"
            >
                {@html closeIcon}
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

<style>
    .toasts-container {
        position: fixed;
        top: 5rem;
        right: 1.5rem;
        z-index: 100;
        width: 100%;
        max-width: 24rem;
        pointer-events: none;
    }

    .toast {
        position: relative;
        display: flex;
        align-items: flex-start;
        padding: 1rem;
        margin-bottom: 0.75rem;
        border-radius: 0.5rem;
        box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
        overflow: hidden;
        pointer-events: auto;
        border-width: 1px;
    }

     .timer {
        position: absolute;
        bottom: 0;
        left: 0;
        height: 3px;
        transform-origin: left;
        transition: transform 0.1s linear;
     }

    @media (max-width: 640px) {
        .toasts-container {
            top: 4.5rem;
            left: 1rem;
            right: 1rem;
            max-width: none;
        }
    }
</style>