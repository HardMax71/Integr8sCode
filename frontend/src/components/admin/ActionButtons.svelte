<script lang="ts">
    import type { Component } from 'svelte';

    interface ActionButton {
        icon: Component;
        label: string;
        onclick: () => void;
        color?: string;
        disabled?: boolean;
        title?: string;
    }

    interface Props {
        actions: ActionButton[];
        variant?: 'icon-only' | 'with-text' | 'mobile';
    }

    let { actions, variant = 'icon-only' }: Props = $props();

    const colorClasses: Record<string, string> = {
        primary: 'text-primary hover:text-primary-dark dark:hover:text-primary-light',
        success: 'text-green-600 hover:text-green-800 dark:text-green-400',
        danger: 'text-red-600 hover:text-red-800 dark:text-red-400',
        warning: 'text-yellow-600 hover:text-yellow-800 dark:text-yellow-400',
        info: 'text-blue-600 hover:text-blue-800 dark:text-blue-400',
        default: 'text-fg-muted hover:text-fg-default dark:hover:text-dark-fg-default'
    };
</script>

{#if variant === 'mobile'}
    <div class="flex gap-2">
        {#each actions as action}
            {@const IconComponent = action.icon}
            <button
                onclick={action.onclick}
                class="flex-1 btn btn-sm btn-outline flex items-center justify-center gap-1 {action.disabled ? 'opacity-50 cursor-not-allowed' : ''}"
                disabled={action.disabled}
                title={action.title || action.label}
            >
                <IconComponent class="w-4 h-4" />
                {action.label}
            </button>
        {/each}
    </div>
{:else if variant === 'with-text'}
    <div class="flex gap-2">
        {#each actions as action}
            {@const IconComponent = action.icon}
            <button
                onclick={action.onclick}
                class="btn btn-sm btn-outline flex items-center gap-1 {colorClasses[action.color || 'default']} {action.disabled ? 'opacity-50 cursor-not-allowed' : ''}"
                disabled={action.disabled}
                title={action.title || action.label}
            >
                <IconComponent class="w-4 h-4" />
                <span class="hidden sm:inline">{action.label}</span>
            </button>
        {/each}
    </div>
{:else}
    <div class="flex gap-2">
        {#each actions as action}
            {@const IconComponent = action.icon}
            <button
                onclick={action.onclick}
                class="{colorClasses[action.color || 'default']} {action.disabled ? 'opacity-50 cursor-not-allowed' : ''}"
                disabled={action.disabled}
                title={action.title || action.label}
            >
                <IconComponent class="w-5 h-5" />
            </button>
        {/each}
    </div>
{/if}
