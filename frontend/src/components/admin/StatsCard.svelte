<script lang="ts">
    import type { Component } from 'svelte';

    interface Props {
        label: string;
        value: string | number;
        sublabel?: string;
        icon?: Component;
        bgColor?: string;
        textColor?: string;
        compact?: boolean;
    }

    let {
        label,
        value,
        sublabel,
        icon: IconComponent,
        bgColor = '',
        textColor = '',
        compact = false
    }: Props = $props();
</script>

<div class="card hover:shadow-lg transition-all duration-200 {bgColor}">
    <div class={compact ? 'p-2 sm:p-3' : 'p-4'}>
        <div class="flex items-center justify-between gap-1">
            <div class="min-w-0 flex-1">
                <p class="text-[10px] sm:text-xs text-fg-muted uppercase tracking-wide mb-0.5 truncate">
                    {label}
                </p>
                <p class="text-base sm:text-lg lg:text-xl font-bold {textColor || 'text-fg-default dark:text-dark-fg-default'}">
                    {value}
                </p>
                {#if sublabel}
                    <p class="text-xs text-fg-muted dark:text-dark-fg-muted">{sublabel}</p>
                {/if}
            </div>
            {#if IconComponent}
                <IconComponent class="w-4 h-4 sm:w-5 sm:h-5 lg:w-6 lg:h-6 text-fg-muted" />
            {/if}
        </div>
    </div>
</div>
