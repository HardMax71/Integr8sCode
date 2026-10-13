<script lang="ts">
    import Modal from '#components/Modal.svelte';

    interface Props {
        open?: boolean;
        title?: string;
        onClose?: () => void;
        showFooter?: boolean;
    }

    let { open = false, title = 'Test Modal', onClose = () => {}, showFooter = false }: Props = $props();
</script>

{#if showFooter}
    <Modal {open} {title} {onClose}>
        <p data-testid="modal-body">Modal body content</p>
        {#snippet footer()}
            <div data-testid="modal-footer-content">Footer content</div>
        {/snippet}
    </Modal>
{:else}
    <Modal {open} {title} {onClose}>
        <p data-testid="modal-body">Modal body content</p>
    </Modal>
{/if}
