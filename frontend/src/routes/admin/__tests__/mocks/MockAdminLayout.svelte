<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    path?: string;
    children: Snippet;
  }

  let { children }: Props = $props();
</script>

<div data-testid="admin-layout">
  {@render children()}
</div>
