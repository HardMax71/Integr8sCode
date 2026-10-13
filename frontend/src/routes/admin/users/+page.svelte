<script lang="ts">
    import { createQuery, keepPreviousData } from '@tanstack/svelte-query';
    import { listUsersApiV1AdminUsersGetOptions, type UserResponse } from '#lib/api/index.ts';
    import Spinner from '#components/Spinner.svelte';
    import { Plus, RefreshCw } from '@lucide/svelte';
    import {
        UserFilters,
        UsersTable,
        UserFormModal,
        DeleteUserModal,
        RateLimitsModal,
    } from '#components/admin/users/index.ts';
    import type { UserListFilters } from '#components/admin/users/UserFilters.svelte';

    // One dialog at a time, with the user it's open for
    let dialog = $state<
        | { kind: 'closed' }
        | { kind: 'create' }
        | { kind: 'edit'; user: UserResponse }
        | { kind: 'delete'; user: UserResponse }
        | { kind: 'rateLimits'; user: UserResponse }
    >({ kind: 'closed' });

    const noFilters = (): UserListFilters => ({
        search: null,
        role: null,
        is_active: null,
        bypass_rate_limit: null,
        has_custom_limits: null,
        custom_multiplier: null,
    });
    let filters = $state(noFilters());
    let showAdvancedFilters = $state(false);

    // Pagination; a new filter goes back to the first page, since the old one may not exist under it
    let pageSize = $state(10);
    let pageIndex = $derived.by(() => {
        void { ...filters };
        return 0;
    });

    const usersQuery = createQuery(() => ({
        ...listUsersApiV1AdminUsersGetOptions({
            query: {
                ...filters,
                search: filters.search || null,
                limit: pageSize,
                offset: pageIndex * pageSize,
            },
        }),
        placeholderData: keepPreviousData,
    }));
    let users = $derived(usersQuery.data?.users ?? []);
    let totalUsers = $derived(usersQuery.data?.total ?? 0);
    let hasFiltersActive = $derived(Object.values(filters).some((value) => value !== null && value !== ''));
</script>

<div class="container mx-auto px-2 sm:px-4 pb-8">
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
        <h1 class="text-2xl sm:text-3xl font-bold text-fg">User Management</h1>
        <div class="flex gap-2 w-full sm:w-auto">
            <button
                type="button"
                onclick={() => (dialog = { kind: 'create' })}
                class="btn btn-primary flex items-center gap-2 flex-1 sm:flex-initial justify-center"
            >
                <Plus class="w-4 h-4" />Create User
            </button>
            <button
                type="button"
                onclick={() => usersQuery.refetch()}
                class="btn btn-secondary-outline flex items-center gap-2 flex-1 sm:flex-initial justify-center"
                disabled={usersQuery.isFetching}
            >
                {#if usersQuery.isFetching}<Spinner size="small" />{:else}<RefreshCw class="w-4 h-4" />{/if}Refresh
            </button>
        </div>
    </div>

    <UserFilters bind:filters bind:showAdvancedFilters {hasFiltersActive} onReset={() => (filters = noFilters())} />

    <div class="card">
        <div class="p-3 sm:p-6">
            <h3 class="text-lg font-semibold text-fg mb-4">
                Users ({totalUsers})
            </h3>

            <UsersTable
                {users}
                rowCount={totalUsers}
                bind:pagination={
                    () => ({ pageIndex, pageSize }),
                    (next) => {
                        pageSize = next.pageSize;
                        pageIndex = next.pageIndex;
                    }
                }
                loading={usersQuery.isPending}
                onEdit={(user) => (dialog = { kind: 'edit', user })}
                onRateLimits={(user) => (dialog = { kind: 'rateLimits', user })}
                onDelete={(user) => (dialog = { kind: 'delete', user })}
            />
        </div>
    </div>
</div>

{#if dialog.kind === 'delete'}
    <DeleteUserModal user={dialog.user} onClose={() => (dialog = { kind: 'closed' })} />
{:else if dialog.kind === 'rateLimits'}
    <RateLimitsModal user={dialog.user} onClose={() => (dialog = { kind: 'closed' })} />
{:else if dialog.kind !== 'closed'}
    <UserFormModal mode={dialog} onClose={() => (dialog = { kind: 'closed' })} />
{/if}
