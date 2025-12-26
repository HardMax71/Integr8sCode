<script lang="ts">
    import { onMount } from 'svelte';
    import {
        listUsersApiV1AdminUsersGet,
        createUserApiV1AdminUsersPost,
        updateUserApiV1AdminUsersUserIdPut,
        deleteUserApiV1AdminUsersUserIdDelete,
        getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet,
        updateUserRateLimitsApiV1AdminUsersUserIdRateLimitsPut,
        resetUserRateLimitsApiV1AdminUsersUserIdRateLimitsResetPost,
        type UserResponse,
        type UserRateLimit,
        type UserRole,
    } from '$lib/api';
    import { unwrap, unwrapOr } from '$lib/api-interceptors';
    import { addToast } from '$stores/toastStore';
    import AdminLayout from '$routes/admin/AdminLayout.svelte';
    import Spinner from '$components/Spinner.svelte';
    import Pagination from '$components/Pagination.svelte';
    import { Plus, RefreshCw } from '@lucide/svelte';
    import {
        UserFilters,
        UsersTable,
        UserFormModal,
        DeleteUserModal,
        RateLimitsModal
    } from '$components/admin/users';

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

    // User list state
    let users = $state<UserResponse[]>([]);
    let loading = $state(false);

    // Modal states
    let showDeleteModal = $state(false);
    let showRateLimitModal = $state(false);
    let showUserModal = $state(false);
    let userToDelete = $state<UserResponse | null>(null);
    let rateLimitUser = $state<UserResponse | null>(null);
    let editingUser = $state<UserResponse | null>(null);

    // Rate limit state
    let rateLimitConfig = $state<UserRateLimit | null>(null);
    let rateLimitUsage = $state<Record<string, { count?: number; tokens_remaining?: number }> | null>(null);
    let loadingRateLimits = $state(false);
    let savingRateLimits = $state(false);

    // User form state
    let userForm = $state({ username: '', email: '', password: '', role: 'user', is_active: true });
    let savingUser = $state(false);
    let cascadeDelete = $state(false);
    let deletingUser = $state(false);

    // Pagination
    let currentPage = $state(1);
    let pageSize = $state(10);

    // Filters
    let searchQuery = $state('');
    let roleFilter = $state<RoleFilter>('all');
    let statusFilter = $state<StatusFilter>('all');
    let showAdvancedFilters = $state(false);
    let advancedFilters = $state<AdvancedFilters>({
        bypassRateLimit: 'all',
        hasCustomLimits: 'all',
        globalMultiplier: 'all'
    });

    // Derived state
    let filteredUsers = $derived(filterUsers(users, searchQuery, roleFilter, statusFilter, advancedFilters));
    let totalPages = $derived(Math.ceil(filteredUsers.length / pageSize));
    let paginatedUsers = $derived(filteredUsers.slice((currentPage - 1) * pageSize, currentPage * pageSize));
    let hasFiltersActive = $derived(
        searchQuery !== '' ||
        roleFilter !== 'all' ||
        statusFilter !== 'all' ||
        advancedFilters.bypassRateLimit !== 'all' ||
        advancedFilters.hasCustomLimits !== 'all' ||
        advancedFilters.globalMultiplier !== 'all'
    );

    onMount(() => { loadUsers(); });

    async function loadUsers(): Promise<void> {
        loading = true;
        const data = unwrapOr(await listUsersApiV1AdminUsersGet({}), null);
        loading = false;
        users = data ? (Array.isArray(data) ? data : data?.users || []) : [];
    }

    function filterUsers(
        userList: UserResponse[],
        search: string,
        role: RoleFilter,
        status: StatusFilter,
        advanced: AdvancedFilters
    ): UserResponse[] {
        let filtered = [...userList];
        if (search) {
            const searchLower = search.toLowerCase();
            filtered = filtered.filter(user =>
                user.username?.toLowerCase().includes(searchLower) ||
                user.email?.toLowerCase().includes(searchLower) ||
                user.user_id?.toLowerCase().includes(searchLower)
            );
        }
        if (role !== 'all') filtered = filtered.filter(user => user.role === role);
        if (status === 'active') filtered = filtered.filter(user => !user.is_disabled);
        else if (status === 'disabled') filtered = filtered.filter(user => user.is_disabled);
        if (advanced.bypassRateLimit === 'yes') filtered = filtered.filter(user => user.bypass_rate_limit === true);
        else if (advanced.bypassRateLimit === 'no') filtered = filtered.filter(user => user.bypass_rate_limit !== true);
        if (advanced.hasCustomLimits === 'yes') filtered = filtered.filter(user => user.has_custom_limits === true);
        else if (advanced.hasCustomLimits === 'no') filtered = filtered.filter(user => user.has_custom_limits !== true);
        if (advanced.globalMultiplier === 'custom') filtered = filtered.filter(user => user.global_multiplier && user.global_multiplier !== 1.0);
        else if (advanced.globalMultiplier === 'default') filtered = filtered.filter(user => !user.global_multiplier || user.global_multiplier === 1.0);
        return filtered;
    }

    // User CRUD
    function openCreateUserModal(): void {
        editingUser = null;
        userForm = { username: '', email: '', password: '', role: 'user', is_active: true };
        showUserModal = true;
    }

    function openEditUserModal(user: UserResponse): void {
        editingUser = user;
        userForm = { username: user.username, email: user.email || '', password: '', role: user.role, is_active: !user.is_disabled };
        showUserModal = true;
    }

    async function saveUser(): Promise<void> {
        if (!userForm.username) { addToast('Username is required', 'error'); return; }
        if (!editingUser && !userForm.password) { addToast('Password is required', 'error'); return; }
        savingUser = true;
        let result;
        if (editingUser) {
            const updateData: Record<string, string | boolean | null> = {
                username: userForm.username, email: userForm.email || null, role: userForm.role, is_active: userForm.is_active
            };
            if (userForm.password) updateData.password = userForm.password;
            result = await updateUserApiV1AdminUsersUserIdPut({ path: { user_id: editingUser.user_id }, body: updateData });
        } else {
            result = await createUserApiV1AdminUsersPost({
                body: { username: userForm.username, email: userForm.email || null, password: userForm.password, role: userForm.role, is_active: userForm.is_active }
            });
        }
        savingUser = false;
        unwrap(result);
        showUserModal = false;
        await loadUsers();
    }

    async function deleteUser(): Promise<void> {
        if (!userToDelete) return;
        deletingUser = true;
        const result = await deleteUserApiV1AdminUsersUserIdDelete({
            path: { user_id: userToDelete.user_id },
            query: { cascade: cascadeDelete }
        });
        deletingUser = false;
        unwrap(result);
        await loadUsers();
        showDeleteModal = false;
        userToDelete = null;
    }

    // Rate limits
    async function openRateLimitModal(user: UserResponse): Promise<void> {
        rateLimitUser = user;
        showRateLimitModal = true;
        loadingRateLimits = true;
        const result = await getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet({
            path: { user_id: user.user_id }
        });
        loadingRateLimits = false;
        const response = unwrap(result);
        rateLimitConfig = response?.rate_limit_config || {
            user_id: user.user_id, rules: [], global_multiplier: 1.0, bypass_rate_limit: false, notes: ''
        };
        rateLimitUsage = response?.current_usage || {};
    }

    async function saveRateLimits(): Promise<void> {
        if (!rateLimitUser || !rateLimitConfig) return;
        savingRateLimits = true;
        const result = await updateUserRateLimitsApiV1AdminUsersUserIdRateLimitsPut({
            path: { user_id: rateLimitUser.user_id },
            body: rateLimitConfig
        });
        savingRateLimits = false;
        unwrap(result);
        showRateLimitModal = false;
    }

    async function resetRateLimits(): Promise<void> {
        if (!rateLimitUser) return;
        unwrap(await resetUserRateLimitsApiV1AdminUsersUserIdRateLimitsResetPost({
            path: { user_id: rateLimitUser.user_id }
        }));
        rateLimitUsage = {};
    }

    function handlePageChange(page: number): void { currentPage = page; }
    function handlePageSizeChange(size: number): void { pageSize = size; currentPage = 1; }

    function resetFilters(): void {
        searchQuery = '';
        roleFilter = 'all';
        statusFilter = 'all';
        advancedFilters = { bypassRateLimit: 'all', hasCustomLimits: 'all', globalMultiplier: 'all' };
        currentPage = 1;
    }

    function handleDelete(user: UserResponse): void {
        userToDelete = user;
        showDeleteModal = true;
    }

    // Reset page when filter changes
    let prevFilters = { searchQuery: '', roleFilter: 'all', statusFilter: 'all' };
    $effect(() => {
        if (searchQuery !== prevFilters.searchQuery || roleFilter !== prevFilters.roleFilter || statusFilter !== prevFilters.statusFilter) {
            prevFilters = { searchQuery, roleFilter, statusFilter };
            currentPage = 1;
        }
    });
</script>

<AdminLayout path="/admin/users">
    <div class="container mx-auto px-2 sm:px-4 pb-8">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
            <h1 class="text-2xl sm:text-3xl font-bold text-fg-default dark:text-dark-fg-default">User Management</h1>
            <div class="flex gap-2 w-full sm:w-auto">
                <button onclick={openCreateUserModal} class="btn btn-primary flex items-center gap-2 flex-1 sm:flex-initial justify-center">
                    <Plus class="w-4 h-4" />Create User
                </button>
                <button onclick={loadUsers} class="btn btn-outline flex items-center gap-2 flex-1 sm:flex-initial justify-center" disabled={loading}>
                    {#if loading}<Spinner size="small" />{:else}<RefreshCw class="w-4 h-4" />{/if}Refresh
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
                    Users ({filteredUsers.length}{filteredUsers.length !== users.length ? ` of ${users.length}` : ''})
                </h3>

                <UsersTable
                    users={paginatedUsers}
                    {loading}
                    onEdit={openEditUserModal}
                    onRateLimits={openRateLimitModal}
                    onDelete={handleDelete}
                />

                {#if totalPages > 1 || filteredUsers.length > 0}
                    <div class="mt-4 border-t divider pt-4">
                        <Pagination
                            {currentPage}
                            {totalPages}
                            totalItems={filteredUsers.length}
                            {pageSize}
                            onPageChange={handlePageChange}
                            onPageSizeChange={handlePageSizeChange}
                            pageSizeOptions={[5, 10, 20, 50]}
                            itemName="users"
                        />
                    </div>
                {/if}
            </div>
        </div>
    </div>
</AdminLayout>

{#if showDeleteModal && userToDelete}
    <DeleteUserModal
        open={showDeleteModal}
        user={userToDelete}
        bind:cascadeDelete
        deleting={deletingUser}
        onClose={() => { showDeleteModal = false; userToDelete = null; }}
        onDelete={deleteUser}
    />
{/if}

{#if showRateLimitModal && rateLimitUser}
    <RateLimitsModal
        open={showRateLimitModal}
        user={rateLimitUser}
        bind:config={rateLimitConfig}
        usage={rateLimitUsage}
        loading={loadingRateLimits}
        saving={savingRateLimits}
        onClose={() => { showRateLimitModal = false; rateLimitUser = null; rateLimitConfig = null; }}
        onSave={saveRateLimits}
        onReset={resetRateLimits}
    />
{/if}

{#if showUserModal}
    <UserFormModal
        open={showUserModal}
        {editingUser}
        bind:form={userForm}
        saving={savingUser}
        onClose={() => showUserModal = false}
        onSave={saveUser}
    />
{/if}
