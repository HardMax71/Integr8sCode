<script lang="ts">
    interface Props {
        status: string;
        color?: string;
        size?: 'sm' | 'md' | 'lg';
        suffix?: string;
    }

    let {
        status,
        color = 'badge-neutral',
        size = 'md',
        suffix
    }: Props = $props();

    const sizeClasses: Record<string, string> = {
        sm: 'text-xs px-1.5 py-0.5',
        md: 'text-sm px-2 py-1',
        lg: 'text-base px-3 py-1.5'
    };
</script>

<span class="badge {color} {sizeClasses[size]}">
    {status}
    {#if suffix}
        <span class="ml-1">{suffix}</span>
    {/if}
</span>
