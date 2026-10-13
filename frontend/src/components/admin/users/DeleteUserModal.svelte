<script lang="ts">
    import { createMutation, useQueryClient } from '@tanstack/svelte-query';
    import {
        deleteUserApiV1AdminUsersUserIdDeleteMutation,
        listUsersApiV1AdminUsersGetQueryKey,
        type UserResponse,
    } from '#lib/api/index.ts';
    import { fieldTitle } from '#lib/formatters.ts';
    import Modal from '#components/Modal.svelte';
    import Spinner from '#components/Spinner.svelte';

    interface Props {
        user: UserResponse;
        onClose: () => void;
    }

    let { user, onClose }: Props = $props();

    let cascade = $state(false);

    const queryClient = useQueryClient();
    const remove = createMutation(() => ({
        ...deleteUserApiV1AdminUsersUserIdDeleteMutation(),
        onSuccess: () => {
            onClose();
            return queryClient.invalidateQueries({ queryKey: listUsersApiV1AdminUsersGetQueryKey() });
        },
    }));
</script>

<Modal open title="Delete User" {onClose} size="sm">
    <p class="mb-4">
        Are you sure you want to delete user <strong>{user.username}</strong>?
    </p>
    <div class="mb-4">
        <label class="flex items-center gap-2">
            <input type="checkbox" bind:checked={cascade} aria-describedby="cascade-description" class="rounded" />
            <span class="text-sm">{fieldTitle('cascade')}</span>
        </label>
        <p id="cascade-description" class="mt-1 text-xs text-fg-muted">
            Also deletes the user's executions, scripts and other data
        </p>
    </div>
    {#if cascade}
        <div class="mb-4 p-3 alert alert-warning">
            <strong>Warning:</strong> This will permanently delete all data associated with this user.
        </div>
    {/if}
    <div class="flex gap-3 justify-end">
        <button type="button" onclick={onClose} class="btn btn-secondary" disabled={remove.isPending}>Cancel</button>
        <button
            type="button"
            onclick={() => remove.mutate({ path: { user_id: user.user_id }, query: { cascade } })}
            class="btn btn-danger gap-2"
            disabled={remove.isPending}
        >
            {#if remove.isPending}
                <Spinner size="small" />Deleting...
            {:else}
                Delete User
            {/if}
        </button>
    </div>
</Modal>
