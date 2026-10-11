<script lang="ts">
    import { untrack } from 'svelte';

    // Calls `run` once while the component initializes, so it can read context such as the query client
    const props: { run: () => void } = $props();
    untrack(() => props.run());
</script>
