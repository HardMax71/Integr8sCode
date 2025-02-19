<script>
    import {onMount} from 'svelte';
    import {notifications, removeNotification} from "../stores/notifications.js";
    import {fly} from "svelte/transition";

    const TIMER_DURATION = 3000; // 3 seconds

    function startTimer(notification) {
        const start = Date.now();
        const timer = setInterval(() => {
            const timeLeft = TIMER_DURATION - (Date.now() - start);
            if (timeLeft <= 0) {
                clearInterval(timer);
                removeNotification(notification.id);
            } else {
                notification.progress = timeLeft / TIMER_DURATION;
                notifications.update(n => n); // Force update to trigger reactivity
            }
        }, 16); // Update roughly every frame (60 FPS)

        return () => clearInterval(timer);
    }

    let mounted = false;

    onMount(() => {
        mounted = true;
        return () => {
            mounted = false;
        };
    });

    $: if (mounted) {
        $notifications.forEach(notif => {
            if (!notif.timerStarted) {
                notif.progress = 1;
                notif.timerStarted = true;
                startTimer(notif);
            }
        });
    }
</script>

<div class="notifications-container">
    {#each $notifications as notification (notification.id)}
        <div class={`notification ${
                    notification.type === 'error'
                      ? 'bg-red-500'
                      : notification.type === 'warning'
                      ? 'bg-yellow-500'
                      : 'bg-green-500'
                  }`}
                in:fly={{ y: 50, duration: 300 }}
                out:fly={{ y: -50, duration: 300 }}>
            <div class="notification-content">
                <span class="block">{notification.message}</span>
            </div>
            <button
                    class="close-button"
                    on:click={() => removeNotification(notification.id)}
                    aria-label="Close notification"
            >
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd"
                          d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                          clip-rule="evenodd"/>
                </svg>
            </button>
            <div
                    class="timer"
                    style="width: {(notification.progress || 1) * 100}%;"
            ></div>
        </div>
    {/each}
</div>

<style>
    :root {
        --header-height: 3rem;
        --notification-width: 20rem;
        --notification-margin: 1rem;
    }

    .notifications-container {
        position: fixed;
        top: calc(var(--header-height) + var(--notification-margin));
        right: var(--notification-margin);
        z-index: 50;
        width: var(--notification-width);
        max-width: calc(100vw - 2 * var(--notification-margin));
    }

    .notification {
        position: relative;
        margin-bottom: 0.5rem;
        padding: 1rem;
        border-radius: 0.375rem;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06);
        color: white;
        overflow: hidden;
    }

    .notification-content {
        padding-right: 2rem;
    }

    .close-button {
        position: absolute;
        top: 0.5rem;
        right: 0.5rem;
        width: 1.5rem;
        height: 1.5rem;
        display: flex;
        align-items: center;
        justify-content: center;
        background: none;
        border: none;
        color: white;
        opacity: 0.7;
        cursor: pointer;
        transition: opacity 0.2s;
    }

    .close-button:hover {
        opacity: 1;
    }

    .timer {
        position: absolute;
        bottom: 0;
        left: 0;
        height: 0.25rem;
        background-color: rgba(255, 255, 255, 0.5);
    }

    @media (max-width: 640px) {
        :root {
            --notification-width: 100%;
            --notification-margin: 0.5rem;
        }

        .notifications-container {
            left: var(--notification-margin);
        }
    }
</style>