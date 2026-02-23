<script lang="ts">
    import type { UserResponse } from '$lib/api';
    import Modal from '$components/Modal.svelte';
    import Spinner from '$components/Spinner.svelte';

    interface Props {
        open: boolean;
        user: UserResponse | null;
        cascadeDelete: boolean;
        deleting: boolean;
        onClose: () => void;
        onDelete: () => void;
        onCascadeChange?: (value: boolean) => void;
    }

    let {
        open,
        user,
        cascadeDelete = $bindable(false),
        deleting,
        onClose,
        onDelete,
        onCascadeChange
    }: Props = $props();

    function handleCascadeChange(e: Event): void {
        const target = e.target as HTMLInputElement;
        cascadeDelete = target.checked;
        onCascadeChange?.(cascadeDelete);
    }
</script>

<Modal {open} title="Delete User" {onClose} size="sm">
    {#snippet children()}
        {#if user}
            <p class="mb-4 text-fg-default dark:text-dark-fg-default">
                Are you sure you want to delete user <strong>{user.username}</strong>?
            </p>
            <div class="mb-4">
                <label class="flex items-center gap-2">
                    <input
                        type="checkbox"
                        checked={cascadeDelete}
                        onchange={handleCascadeChange}
                        class="rounded border-border-default dark:border-dark-border-default"
                    />
                    <span class="text-sm text-fg-default dark:text-dark-fg-default">
                        Delete all user data (executions, scripts, etc.)
                    </span>
                </label>
            </div>
            {#if cascadeDelete}
                <div class="mb-4 p-3 alert alert-warning">
                    <strong>Warning:</strong> This will permanently delete all data associated with this user.
                </div>
            {/if}
            <div class="flex gap-3 justify-end">
                <button type="button" onclick={onClose} class="btn btn-secondary" disabled={deleting}>Cancel</button>
                <button type="button" onclick={onDelete} class="btn btn-danger flex items-center gap-2" disabled={deleting}>
                    {#if deleting}
                        <Spinner size="small" />Deleting...
                    {:else}
                        Delete User
                    {/if}
                </button>
            </div>
        {/if}
    {/snippet}
</Modal>
