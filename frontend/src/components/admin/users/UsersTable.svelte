<script lang="ts">
    import { Pencil, Clock, Trash2 } from '@lucide/svelte';
    import type { UserResponse } from '$lib/api';
    import { formatTimestamp } from '$lib/formatters';

    interface Props {
        users: UserResponse[];
        loading: boolean;
        onEdit: (user: UserResponse) => void;
        onRateLimits: (user: UserResponse) => void;
        onDelete: (user: UserResponse) => void;
    }

    let { users, loading, onEdit, onRateLimits, onDelete }: Props = $props();
</script>

{#if loading}
    <div class="py-8 text-center text-fg-muted dark:text-dark-fg-muted">Loading users...</div>
{:else if users.length === 0}
    <div class="py-8 text-center text-fg-muted dark:text-dark-fg-muted">No users found matching filters</div>
{:else}
    <!-- Mobile Card View -->
    <div class="block lg:hidden">
        {#each users as user}
            <div class="p-4 border-b border-border-default dark:border-dark-border-default hover:bg-neutral-50 dark:hover:bg-neutral-800">
                <div class="flex justify-between items-start mb-3">
                    <div class="flex-1 min-w-0">
                        <div class="font-medium text-fg-default dark:text-dark-fg-default">{user.username}</div>
                        <div class="text-sm text-fg-muted dark:text-dark-fg-muted mt-1">{user.email || 'No email'}</div>
                    </div>
                    <div class="flex gap-2 items-center">
                        <span class="badge {user.role === 'admin' ? 'badge-info' : 'badge-neutral'}">{user.role}</span>
                        <span class="badge {user.is_active ? 'badge-success' : 'badge-danger'}">
                            {user.is_active ? 'Active' : 'Inactive'}
                        </span>
                    </div>
                </div>
                <div class="text-xs text-fg-muted dark:text-dark-fg-muted mb-3">
                    Created: {formatTimestamp(user.created_at)}
                </div>
                <div class="flex gap-2">
                    <button type="button"
                        onclick={() => onEdit(user)}
                        class="flex-1 btn btn-sm btn-outline flex items-center justify-center gap-1"
                    >
                        <Pencil class="w-4 h-4" />Edit
                    </button>
                    <button type="button"
                        onclick={() => onRateLimits(user)}
                        class="flex-1 btn btn-sm btn-outline flex items-center justify-center gap-1"
                    >
                        <Clock class="w-4 h-4" />Limits
                    </button>
                    <button type="button"
                        onclick={() => onDelete(user)}
                        class="btn btn-sm btn-danger flex items-center justify-center gap-1"
                    >
                        <Trash2 class="w-4 h-4" />Delete
                    </button>
                </div>
            </div>
        {/each}
    </div>

    <!-- Desktop Table View -->
    <div class="hidden lg:block overflow-x-auto">
        <table class="table">
            <thead class="table-header">
                <tr>
                    <th class="table-header-cell">Username</th>
                    <th class="table-header-cell">Email</th>
                    <th class="table-header-cell">Role</th>
                    <th class="table-header-cell">Created</th>
                    <th class="table-header-cell">Status</th>
                    <th class="table-header-cell">Actions</th>
                </tr>
            </thead>
            <tbody class="table-body">
                {#each users as user}
                    <tr class="table-row">
                        <td class="table-cell font-medium">{user.username}</td>
                        <td class="table-cell">{user.email || '-'}</td>
                        <td class="table-cell">
                            <span class="badge {user.role === 'admin' ? 'badge-info' : 'badge-neutral'}">{user.role}</span>
                        </td>
                        <td class="table-cell">{formatTimestamp(user.created_at)}</td>
                        <td class="table-cell">
                            <span class="badge {user.is_active ? 'badge-success' : 'badge-danger'}">
                                {user.is_active ? 'Active' : 'Inactive'}
                            </span>
                        </td>
                        <td class="table-cell">
                            <div class="flex gap-2">
                                <button type="button"
                                    onclick={() => onEdit(user)}
                                    class="text-green-600 hover:text-green-800 dark:text-green-400"
                                    title="Edit User"
                                >
                                    <Pencil class="w-5 h-5" />
                                </button>
                                <button type="button"
                                    onclick={() => onRateLimits(user)}
                                    class="text-blue-600 hover:text-blue-800 dark:text-blue-400"
                                    title="Manage Rate Limits"
                                >
                                    <Clock class="w-5 h-5" />
                                </button>
                                <button type="button"
                                    onclick={() => onDelete(user)}
                                    class="text-red-600 hover:text-red-800 dark:text-red-400"
                                    title="Delete User"
                                >
                                    <Trash2 class="w-5 h-5" />
                                </button>
                            </div>
                        </td>
                    </tr>
                {/each}
            </tbody>
        </table>
    </div>
{/if}
