<script lang="ts">
    import type { Component } from 'svelte';
    import { QueryClientProvider } from '@tanstack/svelte-query';
    import { Tooltip } from 'bits-ui';
    import { queryClient } from '#lib/query-client.ts';

    interface Props {
        component: Component<any>;
        props?: Record<string, any>;
    }

    let { component: Inner, props = {} }: Props = $props();
</script>

<QueryClientProvider client={queryClient}>
    <Tooltip.Provider>
        <Inner {...props} />
    </Tooltip.Provider>
</QueryClientProvider>
