<script lang="ts">
  import { X } from '@lucide/svelte';
  import { fade } from 'svelte/transition';
  import type { Snippet } from 'svelte';

  interface Props {
    open: boolean;
    title: string;
    onClose: () => void;
    size?: 'sm' | 'md' | 'lg' | 'xl';
    children: Snippet;
    footer?: Snippet;
  }

  let { open, title, onClose, size = 'lg', children, footer }: Props = $props();

  const sizeClasses = {
    sm: 'max-w-md',
    md: 'max-w-2xl',
    lg: 'max-w-4xl',
    xl: 'max-w-6xl',
  };

  // Only listen for Escape when modal is open
  $effect(() => {
    if (!open) return;

    function handleEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }

    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  });

  function handleBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) onClose();
  }
</script>

{#if open}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    class="modal-backdrop"
    transition:fade={{ duration: 150 }}
    onclick={handleBackdropClick}
    role="dialog"
    aria-modal="true"
    aria-labelledby="modal-title"
  >
    <div class="modal-container {sizeClasses[size]}">
      <div class="modal-header">
        <h2 id="modal-title" class="modal-title">{title}</h2>
        <button onclick={onClose} class="modal-close" aria-label="Close modal">
          <X size={24} />
        </button>
      </div>
      <div class="modal-body">
        {@render children()}
      </div>
      {#if footer}
        <div class="modal-footer">
          {@render footer()}
        </div>
      {/if}
    </div>
  </div>
{/if}
