<script lang="ts">
    let {
        size = 'medium',
        color = 'primary',
        className = '',
    }: {
        size?: 'small' | 'medium' | 'large' | 'xlarge';
        color?: 'primary' | 'white' | 'current' | 'muted';
        className?: string;
    } = $props();

    const sizeClasses: Record<string, string> = {
        small: 'size-4',
        medium: 'size-6',
        large: 'size-8',
        xlarge: 'size-12',
    };

    const colorClasses: Record<string, string> = {
        primary: 'text-accent',
        white: 'text-white',
        current: 'text-current',
        muted: 'text-fg-subtle',
    };

    let sizeClass = $derived(sizeClasses[size] || sizeClasses.medium);
    let colorClass = $derived(colorClasses[color] || colorClasses.primary);
</script>

<svg
    class="animate-spin {sizeClass} {colorClass} {className}"
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
    role="status"
    aria-label="Loading"
>
    <circle class="opacity-20" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2" />
    <path class="opacity-75" fill="currentColor" d="M12 2a10 10 0 00-10 10h2a8 8 0 018-8V2z" />
</svg>
