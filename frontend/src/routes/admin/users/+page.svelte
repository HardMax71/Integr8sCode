<script lang="ts">
    import { createMutation, createQuery, keepPreviousData, useQueryClient } from '@tanstack/svelte-query';
    import {
        listUsersApiV1AdminUsersGetOptions,
        listUsersApiV1AdminUsersGetQueryKey,
        createUserApiV1AdminUsersPostMutation,
        updateUserApiV1AdminUsersUserIdPutMutation,
        deleteUserApiV1AdminUsersUserIdDeleteMutation,
        getUserRateLimitsApiV1AdminRateLimitsUserIdGetOptions,
        getUserRateLimitsApiV1AdminRateLimitsUserIdGetQueryKey,
        updateUserRateLimitsApiV1AdminRateLimitsUserIdPutMutation,
        resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPostMutation,
        zRateLimitUpdateRequest,
        type UserResponse,
        type UserRateLimitConfigResponse,
    } from '#lib/api/index.ts';
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

    // Modal states
    let showDeleteModal = $state(false);
    let showRateLimitModal = $state(false);
    let showUserModal = $state(false);
    let userToDelete = $state<UserResponse | null>(null);
    let rateLimitUser = $state<UserResponse | null>(null);
    let editingUser = $state<UserResponse | null>(null);

    let cascade = $state(false);

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

    const queryClient = useQueryClient();

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

    function invalidateUsers(): Promise<void> {
        return queryClient.invalidateQueries({ queryKey: listUsersApiV1AdminUsersGetQueryKey() });
    }

    const onUserSaved = (): Promise<void> => {
        showUserModal = false;
        return invalidateUsers();
    };
    const createUser = createMutation(() => ({ ...createUserApiV1AdminUsersPostMutation(), onSuccess: onUserSaved }));
    const updateUser = createMutation(() => ({
        ...updateUserApiV1AdminUsersUserIdPutMutation(),
        onSuccess: onUserSaved,
    }));
    const removeUser = createMutation(() => ({
        ...deleteUserApiV1AdminUsersUserIdDeleteMutation(),
        onSuccess: () => {
            showDeleteModal = false;
            userToDelete = null;
            return invalidateUsers();
        },
    }));

    const rateLimits = createQuery(() => ({
        ...getUserRateLimitsApiV1AdminRateLimitsUserIdGetOptions({ path: { user_id: rateLimitUser?.user_id ?? '' } }),
        enabled: rateLimitUser !== null,
    }));
    let loadedRateLimitConfig = $derived(rateLimits.data?.rate_limit_config);
    // Edits go to a copy; structural sharing keeps the loaded config across an unchanged refetch, so they survive it
    let rateLimitConfig = $derived.by(() => {
        const loaded = loadedRateLimitConfig;
        const user = rateLimitUser;
        const draft = $state<UserRateLimitConfigResponse | null>(
            loaded === undefined || !user
                ? null
                : structuredClone(
                      loaded ?? {
                          user_id: user.user_id,
                          notes: null,
                          created_at: null,
                          updated_at: null,
                          ...zRateLimitUpdateRequest.parse({}),
                      },
                  ),
        );
        return draft;
    });
    const saveRateLimitsMutation = createMutation(() => ({
        ...updateUserRateLimitsApiV1AdminRateLimitsUserIdPutMutation(),
        onSuccess: (_data, { path }) => {
            showRateLimitModal = false;
            return Promise.all([
                invalidateUsers(),
                queryClient.invalidateQueries({
                    queryKey: getUserRateLimitsApiV1AdminRateLimitsUserIdGetQueryKey({ path }),
                }),
            ]);
        },
    }));
    const resetRateLimitsMutation = createMutation(() => ({
        ...resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPostMutation(),
        onSuccess: (_data, { path }) =>
            queryClient.invalidateQueries({
                queryKey: getUserRateLimitsApiV1AdminRateLimitsUserIdGetQueryKey({ path }),
            }),
    }));

    let hasFiltersActive = $derived(Object.values(filters).some((value) => value !== null && value !== ''));

    // User CRUD
    function openUserModal(user: UserResponse | null): void {
        editingUser = user;
        showUserModal = true;
    }

    function deleteUser(): void {
        if (!userToDelete) return;
        removeUser.mutate({ path: { user_id: userToDelete.user_id }, query: { cascade } });
    }

    // Rate limits
    function openRateLimitModal(user: UserResponse): void {
        rateLimitUser = user;
        showRateLimitModal = true;
    }

    function saveRateLimits(): void {
        if (!rateLimitUser || !rateLimitConfig) return;
        saveRateLimitsMutation.mutate({
            path: { user_id: rateLimitUser.user_id },
            body: zRateLimitUpdateRequest.parse($state.snapshot(rateLimitConfig)),
        });
    }

    function resetRateLimits(): void {
        if (!rateLimitUser) return;
        resetRateLimitsMutation.mutate({ path: { user_id: rateLimitUser.user_id } });
    }

    function resetFilters(): void {
        filters = noFilters();
    }

    function handleDelete(user: UserResponse): void {
        userToDelete = user;
        showDeleteModal = true;
    }
</script>

<div class="container mx-auto px-2 sm:px-4 pb-8">
    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
        <h1 class="text-2xl sm:text-3xl font-bold text-fg-default dark:text-dark-fg-default">User Management</h1>
        <div class="flex gap-2 w-full sm:w-auto">
            <button
                type="button"
                onclick={() => openUserModal(null)}
                class="btn btn-primary flex items-center gap-2 flex-1 sm:flex-initial justify-center"
            >
                <Plus class="w-4 h-4" />Create User
            </button>
            <button
                type="button"
                onclick={invalidateUsers}
                class="btn btn-secondary-outline flex items-center gap-2 flex-1 sm:flex-initial justify-center"
                disabled={usersQuery.isFetching}
            >
                {#if usersQuery.isFetching}<Spinner size="small" />{:else}<RefreshCw class="w-4 h-4" />{/if}Refresh
            </button>
        </div>
    </div>

    <UserFilters bind:filters bind:showAdvancedFilters {hasFiltersActive} onReset={resetFilters} />

    <div class="card">
        <div class="p-3 sm:p-6">
            <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">
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
                onEdit={openUserModal}
                onRateLimits={openRateLimitModal}
                onDelete={handleDelete}
            />
        </div>
    </div>
</div>

{#if showDeleteModal && userToDelete}
    <DeleteUserModal
        open={showDeleteModal}
        user={userToDelete}
        bind:cascade
        deleting={removeUser.isPending}
        onClose={() => {
            showDeleteModal = false;
            userToDelete = null;
        }}
        onDelete={deleteUser}
    />
{/if}

{#if showRateLimitModal && rateLimitUser}
    <RateLimitsModal
        open={showRateLimitModal}
        user={rateLimitUser}
        bind:config={rateLimitConfig}
        usage={rateLimits.data?.current_usage ?? null}
        loading={rateLimits.isPending}
        saving={saveRateLimitsMutation.isPending}
        onClose={() => {
            showRateLimitModal = false;
            rateLimitUser = null;
        }}
        onSave={saveRateLimits}
        onReset={resetRateLimits}
    />
{/if}

{#if showUserModal}
    <UserFormModal
        open={showUserModal}
        {editingUser}
        saving={createUser.isPending || updateUser.isPending}
        onClose={() => (showUserModal = false)}
        onCreate={(body) => createUser.mutate({ body })}
        onEdit={(userId, body) => updateUser.mutate({ path: { user_id: userId }, body })}
    />
{/if}
