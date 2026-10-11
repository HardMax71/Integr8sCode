<script lang="ts">
    import * as z from 'zod/mini';
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
        type UserResponse,
        type UserRateLimitConfigResponse,
        type UserRole,
        type UserCreate,
        type UserUpdate,
        zUserCreate,
        zUserUpdate,
    } from '#lib/api/index.ts';
    import { firstIssue } from '#lib/validation.ts';
    import { toast } from 'svelte-sonner';
    import Spinner from '#components/Spinner.svelte';
    import { Plus, RefreshCw } from '@lucide/svelte';
    import {
        UserFilters,
        UsersTable,
        UserFormModal,
        DeleteUserModal,
        RateLimitsModal,
    } from '#components/admin/users/index.ts';

    // Filter types - 'all' means no filter applied
    type RoleFilter = 'all' | UserRole;
    type StatusFilter = 'all' | 'active' | 'disabled';
    type BooleanFilter = 'all' | 'yes' | 'no';
    type MultiplierFilter = 'all' | 'custom' | 'default';

    interface AdvancedFilters {
        bypassRateLimit: BooleanFilter;
        hasCustomLimits: BooleanFilter;
        globalMultiplier: MultiplierFilter;
    }

    // Modal states
    let showDeleteModal = $state(false);
    let showRateLimitModal = $state(false);
    let showUserModal = $state(false);
    let userToDelete = $state<UserResponse | null>(null);
    let rateLimitUser = $state<UserResponse | null>(null);
    let editingUser = $state<UserResponse | null>(null);

    // User form state, with role and is_active defaulted the way the API defaults them
    const blankUserForm = (): Required<UserCreate> => ({
        username: '',
        email: '',
        password: '',
        ...z.pick(zUserCreate, { role: true, is_active: true }).parse({}),
    });
    let userForm = $state<Required<UserCreate>>(blankUserForm());
    let cascadeDelete = $state(false);

    // Filters
    let searchQuery = $state('');
    let roleFilter = $state<RoleFilter>('all');
    let statusFilter = $state<StatusFilter>('all');
    let showAdvancedFilters = $state(false);
    let advancedFilters = $state<AdvancedFilters>({
        bypassRateLimit: 'all',
        hasCustomLimits: 'all',
        globalMultiplier: 'all',
    });

    // Pagination; a new filter goes back to the first page, since the old one may not exist under it
    let pageSize = $state(10);
    let pageIndex = $derived.by(() => {
        void [searchQuery, roleFilter, statusFilter, { ...advancedFilters }];
        return 0;
    });

    const queryClient = useQueryClient();

    const yesNo = (filter: BooleanFilter): boolean | null => (filter === 'all' ? null : filter === 'yes');

    const usersQuery = createQuery(() => ({
        ...listUsersApiV1AdminUsersGetOptions({
            query: {
                search: searchQuery || null,
                role: roleFilter !== 'all' ? roleFilter : null,
                is_active: statusFilter === 'all' ? null : statusFilter === 'active',
                bypass_rate_limit: yesNo(advancedFilters.bypassRateLimit),
                has_custom_limits: yesNo(advancedFilters.hasCustomLimits),
                custom_multiplier:
                    advancedFilters.globalMultiplier === 'all' ? null : advancedFilters.globalMultiplier === 'custom',
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
                          rules: [],
                          global_multiplier: 1.0,
                          bypass_rate_limit: false,
                          notes: '',
                          created_at: null,
                          updated_at: null,
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

    let hasFiltersActive = $derived(
        searchQuery !== '' ||
            roleFilter !== 'all' ||
            statusFilter !== 'all' ||
            advancedFilters.bypassRateLimit !== 'all' ||
            advancedFilters.hasCustomLimits !== 'all' ||
            advancedFilters.globalMultiplier !== 'all',
    );

    // User CRUD
    function openCreateUserModal(): void {
        editingUser = null;
        userForm = blankUserForm();
        showUserModal = true;
    }

    function openEditUserModal(user: UserResponse): void {
        editingUser = user;
        userForm = {
            username: user.username,
            email: user.email || '',
            password: '',
            role: user.role,
            is_active: user.is_active !== false,
        };
        showUserModal = true;
    }

    function saveUser(): void {
        if (editingUser) {
            const updateData: UserUpdate = {
                username: userForm.username,
                email: userForm.email || null,
                role: userForm.role,
                is_active: userForm.is_active,
            };
            if (userForm.password) updateData.password = userForm.password;
            const parsed = zUserUpdate.safeParse(updateData);
            if (!parsed.success) {
                toast.error(firstIssue(parsed.error));
                return;
            }
            updateUser.mutate({ path: { user_id: editingUser.user_id }, body: parsed.data });
        } else {
            const parsed = zUserCreate.safeParse(userForm);
            if (!parsed.success) {
                toast.error(firstIssue(parsed.error));
                return;
            }
            createUser.mutate({ body: parsed.data });
        }
    }

    function deleteUser(): void {
        if (!userToDelete) return;
        removeUser.mutate({ path: { user_id: userToDelete.user_id }, query: { cascade: cascadeDelete } });
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
            body: $state.snapshot(rateLimitConfig),
        });
    }

    function resetRateLimits(): void {
        if (!rateLimitUser) return;
        resetRateLimitsMutation.mutate({ path: { user_id: rateLimitUser.user_id } });
    }

    function resetFilters(): void {
        searchQuery = '';
        roleFilter = 'all';
        statusFilter = 'all';
        advancedFilters = { bypassRateLimit: 'all', hasCustomLimits: 'all', globalMultiplier: 'all' };
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
                onclick={openCreateUserModal}
                class="btn btn-primary flex items-center gap-2 flex-1 sm:flex-initial justify-center"
            >
                <Plus class="w-4 h-4" />Create User
            </button>
            <button
                type="button"
                onclick={invalidateUsers}
                class="btn btn-outline flex items-center gap-2 flex-1 sm:flex-initial justify-center"
                disabled={usersQuery.isFetching}
            >
                {#if usersQuery.isFetching}<Spinner size="small" />{:else}<RefreshCw class="w-4 h-4" />{/if}Refresh
            </button>
        </div>
    </div>

    <UserFilters
        bind:searchQuery
        bind:roleFilter
        bind:statusFilter
        bind:advancedFilters
        bind:showAdvancedFilters
        {hasFiltersActive}
        onReset={resetFilters}
    />

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
                onEdit={openEditUserModal}
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
        bind:cascadeDelete
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
        bind:form={userForm}
        saving={createUser.isPending || updateUser.isPending}
        onClose={() => (showUserModal = false)}
        onSave={saveUser}
    />
{/if}
