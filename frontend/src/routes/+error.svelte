<script lang="ts">
    import { page } from '$app/state';
    import ErrorDisplay from '#components/ErrorDisplay.svelte';
</script>

<svelte:head>
    <title>{page.status === 404 ? 'Page not found' : 'Error'} - Integr8sCode</title>
</svelte:head>

<ErrorDisplay
    error={page.error?.message ?? 'Unknown error'}
    title={page.status === 404 ? 'Page not found' : 'Something went wrong'}
/>
