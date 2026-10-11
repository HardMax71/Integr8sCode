<script lang="ts">
    import type { Component } from 'svelte';
    import { QueryClientProvider } from '@tanstack/svelte-query';
    import { queryClient } from '#lib/query-client.ts';

    interface Props {
        component: Component<any>;
        props?: Record<string, any>;
    }

    let { component: Inner, props = {} }: Props = $props();
</script>

<QueryClientProvider client={queryClient}>
    <Inner {...props} />
</QueryClientProvider>
