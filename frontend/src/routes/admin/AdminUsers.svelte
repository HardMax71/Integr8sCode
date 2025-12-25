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
        type RateLimitRule,
        type EndpointGroup,
    } from '../../lib/api';
    import { unwrap, unwrapOr } from '../../lib/api-interceptors';
    import { addToast } from '../../stores/toastStore';
    import { formatTimestamp } from '../../lib/formatters';
    import AdminLayout from './AdminLayout.svelte';
    import Spinner from '../../components/Spinner.svelte';
    import Modal from '../../components/Modal.svelte';
    import Pagination from '../../components/Pagination.svelte';
    import { Plus, RefreshCw, Pencil, Clock, Trash2, ChevronDown, X } from '@lucide/svelte';

    let users = $state<UserResponse[]>([]);
    let loading = $state(false);
    let showDeleteModal = $state(false);
    let showRateLimitModal = $state(false);
    let userToDelete = $state<UserResponse | null>(null);
    let rateLimitUser = $state<UserResponse | null>(null);
    let rateLimitConfig = $state<UserRateLimit | null>(null);
    let rateLimitUsage = $state<Record<string, number> | null>(null);
    let cascadeDelete = $state(true);
    let deletingUser = $state(false);
    let loadingRateLimits = $state(false);
    let savingRateLimits = $state(false);

    let currentPage = $state(1);
    let pageSize = $state(10);

    let searchQuery = $state('');
    let roleFilter = $state('all');
    let statusFilter = $state('all');
    let showAdvancedFilters = $state(false);
    let advancedFilters = $state({
        bypassRateLimit: 'all' as string,
        hasCustomLimits: 'all' as string,
        globalMultiplier: 'all' as string
    });

    let showUserModal = $state(false);
    let editingUser = $state<UserResponse | null>(null);
    let userForm = $state({ username: '', email: '', password: '', role: 'user', is_active: true });
    let savingUser = $state(false);

    let filteredUsers = $derived(filterUsers(users, searchQuery, roleFilter, statusFilter, advancedFilters));
    let totalPages = $derived(Math.ceil(filteredUsers.length / pageSize));
    let paginatedUsers = $derived(filteredUsers.slice((currentPage - 1) * pageSize, currentPage * pageSize));

    onMount(() => { loadUsers(); });

    async function loadUsers(): Promise<void> {
        loading = true;
        const data = unwrapOr(await listUsersApiV1AdminUsersGet({}), null);
        loading = false;
        users = data ? (Array.isArray(data) ? data : data?.users || []) : [];
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

    let defaultRulesWithEffective = $derived(getDefaultRulesWithMultiplier(rateLimitConfig?.global_multiplier));

    function getDefaultRulesWithMultiplier(multiplier: number): RateLimitRule[] {
        const rules = [
            { endpoint_pattern: '^/api/v1/execute', group: 'execution', requests: 10, window_seconds: 60, algorithm: 'sliding_window', priority: 10 },
            { endpoint_pattern: '^/api/v1/admin/.*', group: 'admin', requests: 100, window_seconds: 60, algorithm: 'sliding_window', priority: 5 },
            { endpoint_pattern: '^/api/v1/events/.*', group: 'sse', requests: 5, window_seconds: 60, algorithm: 'sliding_window', priority: 8 },
            { endpoint_pattern: '^/api/v1/ws', group: 'websocket', requests: 5, window_seconds: 60, algorithm: 'sliding_window', priority: 8 },
            { endpoint_pattern: '^/api/v1/auth/.*', group: 'auth', requests: 20, window_seconds: 60, algorithm: 'sliding_window', priority: 7 },
            { endpoint_pattern: '^/api/v1/.*', group: 'api', requests: 60, window_seconds: 60, algorithm: 'sliding_window', priority: 1 }
        ];
        const effectiveMultiplier = multiplier || 1.0;
        return rules.map(rule => ({ ...rule, effective_requests: Math.floor(rule.requests * effectiveMultiplier) }));
    }

    const groupColors: Record<string, string> = {
        execution: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
        admin: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
        sse: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
        websocket: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
        auth: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
        api: 'bg-neutral-100 text-neutral-800 dark:bg-neutral-700 dark:text-neutral-200',
        public: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200'
    };

    function getGroupColor(group: EndpointGroup | string): string {
        return groupColors[group] || groupColors.api;
    }

    const endpointGroupPatterns = [
        { pattern: /\/execute/i, group: 'execution' }, { pattern: /\/admin\//i, group: 'admin' },
        { pattern: /\/events\//i, group: 'sse' }, { pattern: /\/ws/i, group: 'websocket' },
        { pattern: /\/auth\//i, group: 'auth' }, { pattern: /\/health/i, group: 'public' }
    ];

    function detectGroupFromEndpoint(endpoint: string): string {
        const cleanEndpoint = endpoint.replace(/^\^?/, '').replace(/\$?/, '').replace(/\.\*/g, '');
        for (const { pattern, group } of endpointGroupPatterns) {
            if (pattern.test(cleanEndpoint)) return group;
        }
        return 'api';
    }

    function handleEndpointChange(rule: RateLimitRule): void {
        if (rule.endpoint_pattern) rule.group = detectGroupFromEndpoint(rule.endpoint_pattern);
    }

    function addNewRule(): void {
        if (!rateLimitConfig?.rules) rateLimitConfig!.rules = [];
        rateLimitConfig!.rules = [...rateLimitConfig!.rules, {
            endpoint_pattern: '', group: 'api', requests: 60, window_seconds: 60,
            burst_multiplier: 1.5, algorithm: 'sliding_window', priority: 0, enabled: true
        }];
    }

    function removeRule(index: number): void {
        rateLimitConfig!.rules = rateLimitConfig!.rules!.filter((_, i) => i !== index);
    }

    interface AdvancedFilters { bypassRateLimit: string; hasCustomLimits: string; globalMultiplier: string; }

    function filterUsers(userList: UserResponse[], search: string, role: string, status: string, advanced: AdvancedFilters): UserResponse[] {
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

    function handlePageChange(page: number): void { currentPage = page; }
    function handlePageSizeChange(size: number): void { pageSize = size; currentPage = 1; }

    function resetFilters(): void {
        searchQuery = ''; roleFilter = 'all'; statusFilter = 'all';
        advancedFilters = { bypassRateLimit: 'all', hasCustomLimits: 'all', globalMultiplier: 'all' };
        currentPage = 1;
    }

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

        <!-- Search and Filters -->
        <div class="card mb-4">
            <div class="p-3 sm:p-4">
                <div class="flex flex-col lg:flex-row gap-3 lg:gap-4 lg:items-end">
                    <div class="w-full lg:flex-1 lg:max-w-md">
                        <label for="user-search" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Search</label>
                        <input id="user-search" type="text" bind:value={searchQuery} placeholder="Search by username, email, or ID..."
                            class="input w-full" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" />
                    </div>
                    <div class="w-full sm:w-auto sm:min-w-[140px]">
                        <label for="role-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Role</label>
                        <select id="role-filter" bind:value={roleFilter} class="form-select-standard w-full">
                            <option value="all">All Roles</option><option value="user">User</option><option value="admin">Admin</option>
                        </select>
                    </div>
                    <div class="w-full sm:w-auto sm:min-w-[140px]">
                        <label for="status-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Status</label>
                        <select id="status-filter" bind:value={statusFilter} class="form-select-standard w-full">
                            <option value="all">All Status</option><option value="active">Active</option><option value="disabled">Disabled</option>
                        </select>
                    </div>
                    <button onclick={() => showAdvancedFilters = !showAdvancedFilters} class="btn btn-outline flex items-center gap-2 w-full sm:w-auto justify-center">
                        <ChevronDown class="w-4 h-4 transition-transform {showAdvancedFilters ? 'rotate-180' : ''}" />Advanced
                    </button>
                    <button onclick={resetFilters} class="btn btn-outline w-full sm:w-auto"
                        disabled={!searchQuery && roleFilter === 'all' && statusFilter === 'all' &&
                                 advancedFilters.bypassRateLimit === 'all' && advancedFilters.hasCustomLimits === 'all' && advancedFilters.globalMultiplier === 'all'}>
                        Reset
                    </button>
                </div>

                {#if showAdvancedFilters}
                    <div class="mt-4 pt-4 border-t border-neutral-200 dark:border-neutral-700">
                        <h4 class="text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-3">Rate Limit Filters</h4>
                        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                            <div>
                                <label for="bypass-rate-limit-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Bypass Rate Limit</label>
                                <select id="bypass-rate-limit-filter" bind:value={advancedFilters.bypassRateLimit} class="form-select-standard w-full">
                                    <option value="all">All</option><option value="yes">Yes (Bypassed)</option><option value="no">No (Limited)</option>
                                </select>
                            </div>
                            <div>
                                <label for="custom-limits-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Custom Limits</label>
                                <select id="custom-limits-filter" bind:value={advancedFilters.hasCustomLimits} class="form-select-standard w-full">
                                    <option value="all">All</option><option value="yes">Has Custom</option><option value="no">Default Only</option>
                                </select>
                            </div>
                            <div>
                                <label for="global-multiplier-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Global Multiplier</label>
                                <select id="global-multiplier-filter" bind:value={advancedFilters.globalMultiplier} class="form-select-standard w-full">
                                    <option value="all">All</option><option value="custom">Custom (≠ 1.0)</option><option value="default">Default (= 1.0)</option>
                                </select>
                            </div>
                        </div>
                    </div>
                {/if}
            </div>
        </div>

        <div class="card">
            <div class="p-3 sm:p-6">
                <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">
                    Users ({filteredUsers.length}{filteredUsers.length !== users.length ? ` of ${users.length}` : ''})
                </h3>

                {#if loading}
                    <div class="py-8 text-center text-fg-muted dark:text-dark-fg-muted">Loading users...</div>
                {:else if filteredUsers.length === 0}
                    <div class="py-8 text-center text-fg-muted dark:text-dark-fg-muted">No users found matching filters</div>
                {:else}
                    <!-- Mobile Card View -->
                    <div class="block lg:hidden">
                        {#each paginatedUsers as user}
                            <div class="p-4 border-b border-border-default dark:border-dark-border-default hover:bg-neutral-50 dark:hover:bg-neutral-800">
                                <div class="flex justify-between items-start mb-3">
                                    <div class="flex-1 min-w-0">
                                        <div class="font-medium text-fg-default dark:text-dark-fg-default">{user.username}</div>
                                        <div class="text-sm text-fg-muted dark:text-dark-fg-muted mt-1">{user.email || 'No email'}</div>
                                    </div>
                                    <div class="flex gap-2 items-center">
                                        <span class="badge {user.role === 'admin' ? 'badge-info' : 'badge-neutral'}">{user.role}</span>
                                        <span class="badge {user.is_active ? 'badge-success' : 'badge-danger'}">{user.is_active ? 'Active' : 'Inactive'}</span>
                                    </div>
                                </div>
                                <div class="text-xs text-fg-muted dark:text-dark-fg-muted mb-3">Created: {formatTimestamp(user.created_at)}</div>
                                <div class="flex gap-2">
                                    <button onclick={() => openEditUserModal(user)} class="flex-1 btn btn-sm btn-outline flex items-center justify-center gap-1">
                                        <Pencil class="w-4 h-4" />Edit
                                    </button>
                                    <button onclick={() => openRateLimitModal(user)} class="flex-1 btn btn-sm btn-outline flex items-center justify-center gap-1">
                                        <Clock class="w-4 h-4" />Limits
                                    </button>
                                    <button onclick={() => { userToDelete = user; showDeleteModal = true; }} class="btn btn-sm btn-danger flex items-center justify-center gap-1">
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
                                {#each paginatedUsers as user}
                                    <tr class="table-row">
                                        <td class="table-cell font-medium">{user.username}</td>
                                        <td class="table-cell">{user.email || '-'}</td>
                                        <td class="table-cell"><span class="badge {user.role === 'admin' ? 'badge-info' : 'badge-neutral'}">{user.role}</span></td>
                                        <td class="table-cell">{formatTimestamp(user.created_at)}</td>
                                        <td class="table-cell"><span class="badge {user.is_active ? 'badge-success' : 'badge-danger'}">{user.is_active ? 'Active' : 'Inactive'}</span></td>
                                        <td class="table-cell">
                                            <div class="flex gap-2">
                                                <button onclick={() => openEditUserModal(user)} class="text-green-600 hover:text-green-800 dark:text-green-400" title="Edit User">
                                                    <Pencil class="w-5 h-5" />
                                                </button>
                                                <button onclick={() => openRateLimitModal(user)} class="text-blue-600 hover:text-blue-800 dark:text-blue-400" title="Manage Rate Limits">
                                                    <Clock class="w-5 h-5" />
                                                </button>
                                                <button onclick={() => { userToDelete = user; showDeleteModal = true; }} class="text-red-600 hover:text-red-800 dark:text-red-400" title="Delete User">
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

                {#if totalPages > 1 || filteredUsers.length > 0}
                    <div class="mt-4 border-t divider pt-4">
                        <Pagination {currentPage} {totalPages} totalItems={filteredUsers.length} {pageSize}
                            onPageChange={handlePageChange} onPageSizeChange={handlePageSizeChange} pageSizeOptions={[5, 10, 20, 50]} itemName="users" />
                    </div>
                {/if}
            </div>
        </div>
    </div>
</AdminLayout>

<!-- Delete User Modal -->
{#if showDeleteModal && userToDelete}
<Modal open={showDeleteModal} title="Delete User" onClose={() => { showDeleteModal = false; userToDelete = null; }} size="sm">
    {#snippet children()}
        <p class="mb-4 text-fg-default dark:text-dark-fg-default">
            Are you sure you want to delete user <strong>{userToDelete.username}</strong>?
        </p>
        <div class="mb-4">
            <label class="flex items-center gap-2">
                <input type="checkbox" bind:checked={cascadeDelete} class="rounded border-border-default dark:border-dark-border-default" />
                <span class="text-sm text-fg-default dark:text-dark-fg-default">Delete all user data (executions, scripts, etc.)</span>
            </label>
        </div>
        {#if cascadeDelete}
            <div class="mb-4 p-3 alert alert-warning">
                <strong>Warning:</strong> This will permanently delete all data associated with this user.
            </div>
        {/if}
        <div class="flex gap-3 justify-end">
            <button onclick={() => { showDeleteModal = false; userToDelete = null; }} class="btn btn-secondary" disabled={deletingUser}>Cancel</button>
            <button onclick={deleteUser} class="btn btn-danger flex items-center gap-2" disabled={deletingUser}>
                {#if deletingUser}<Spinner size="small" />Deleting...{:else}Delete User{/if}
            </button>
        </div>
    {/snippet}
</Modal>
{/if}

<!-- Rate Limit Modal -->
{#if showRateLimitModal && rateLimitUser}
<Modal open={showRateLimitModal} title="Rate Limits for {rateLimitUser.username}" onClose={() => { showRateLimitModal = false; rateLimitUser = null; rateLimitConfig = null; }} size="xl">
    {#snippet children()}
        {#if loadingRateLimits}
            <div class="flex justify-center py-8"><Spinner /></div>
        {:else if rateLimitConfig}
            <div class="space-y-4">
                <!-- Quick Settings -->
                <div class="border border-neutral-200 dark:border-neutral-700 rounded-lg p-4 bg-neutral-50 dark:bg-neutral-900">
                    <div class="flex items-center justify-between mb-3">
                        <h4 class="font-semibold text-fg-default dark:text-dark-fg-default">Quick Settings</h4>
                        <label class="flex items-center gap-2">
                            <input type="checkbox" bind:checked={rateLimitConfig.bypass_rate_limit} class="rounded" />
                            <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Bypass all rate limits</span>
                        </label>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                            <label for="global-multiplier" class="block text-sm font-medium mb-1 text-fg-default dark:text-dark-fg-default">Global Multiplier</label>
                            <input id="global-multiplier" type="number" bind:value={rateLimitConfig.global_multiplier} min="0.01" step="0.1"
                                class="input w-full" disabled={rateLimitConfig.bypass_rate_limit} />
                            <p class="text-xs text-neutral-500 dark:text-neutral-400 mt-1">Multiplies all limits (1.0 = default, 2.0 = double)</p>
                        </div>
                        <div>
                            <label for="admin-notes" class="block text-sm font-medium mb-1 text-fg-default dark:text-dark-fg-default">Admin Notes</label>
                            <textarea id="admin-notes" bind:value={rateLimitConfig.notes} rows="2" class="input w-full text-sm" placeholder="Notes about this user's rate limits..."></textarea>
                        </div>
                    </div>
                </div>

                <!-- Endpoint-Specific Limits -->
                <div class="border border-neutral-200 dark:border-neutral-700 rounded-lg p-4">
                    <div class="flex justify-between items-center mb-4">
                        <h4 class="font-semibold text-fg-default dark:text-dark-fg-default">Endpoint Rate Limits</h4>
                        <button onclick={() => addNewRule()} class="btn btn-sm btn-primary flex items-center gap-1" disabled={rateLimitConfig.bypass_rate_limit}>
                            <Plus class="w-4 h-4" />Add Rule
                        </button>
                    </div>

                    <!-- Default Rules -->
                    <div class="mb-4">
                        <h5 class="text-xs sm:text-sm font-medium text-neutral-600 dark:text-neutral-400 mb-2">Default Global Rules</h5>
                        <div class="space-y-2">
                            {#each defaultRulesWithEffective || [] as rule}
                                <div class="flex items-center justify-between p-3 bg-neutral-50 dark:bg-neutral-900 rounded-lg">
                                    <div class="flex-1 grid grid-cols-2 lg:grid-cols-4 gap-2 lg:gap-4 items-center">
                                        <div>
                                            <span class="text-xs text-neutral-500 dark:text-neutral-400">Endpoint</span>
                                            <p class="text-sm font-mono text-fg-default dark:text-dark-fg-default">{rule.endpoint_pattern}</p>
                                        </div>
                                        <div>
                                            <span class="text-xs text-neutral-500 dark:text-neutral-400">Limit</span>
                                            <p class="text-sm text-fg-default dark:text-dark-fg-default">
                                                {#if rateLimitConfig?.global_multiplier !== 1.0}
                                                    <span class="line-through text-neutral-400">{rule.requests}</span>
                                                    <span class="font-semibold text-blue-600 dark:text-blue-400">{rule.effective_requests}</span>
                                                {:else}{rule.requests}{/if} req / {rule.window_seconds}s
                                            </p>
                                        </div>
                                        <div>
                                            <span class="text-xs text-neutral-500 dark:text-neutral-400">Group</span>
                                            <span class="inline-block px-2 py-1 text-xs rounded-full {getGroupColor(rule.group)}">{rule.group}</span>
                                        </div>
                                        <div>
                                            <span class="text-xs text-neutral-500 dark:text-neutral-400">Algorithm</span>
                                            <p class="text-sm text-fg-default dark:text-dark-fg-default">{rule.algorithm}</p>
                                        </div>
                                    </div>
                                </div>
                            {/each}
                        </div>
                    </div>

                    <!-- User-Specific Rules -->
                    {#if rateLimitConfig.rules && rateLimitConfig.rules.length > 0}
                        <div>
                            <h5 class="text-xs sm:text-sm font-medium text-neutral-600 dark:text-neutral-400 mb-2">User-Specific Overrides</h5>
                            <div class="space-y-2">
                                {#each rateLimitConfig.rules as rule, index}
                                    <div class="p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
                                        <div class="flex flex-col lg:flex-row items-start lg:items-center gap-3">
                                            <div class="w-full lg:flex-1 lg:min-w-[200px]">
                                                <input type="text" bind:value={rule.endpoint_pattern} oninput={() => handleEndpointChange(rule)}
                                                    placeholder="Endpoint pattern" class="input input-sm w-full" disabled={rateLimitConfig.bypass_rate_limit} />
                                            </div>
                                            <div class="flex items-center gap-1 flex-wrap">
                                                <input type="number" bind:value={rule.requests} min="1" class="input input-sm w-16" disabled={rateLimitConfig.bypass_rate_limit} />
                                                <span class="text-xs text-neutral-500">/</span>
                                                <input type="number" bind:value={rule.window_seconds} min="1" class="input input-sm w-16" disabled={rateLimitConfig.bypass_rate_limit} />
                                                <span class="text-xs text-neutral-500">s</span>
                                                {#if rateLimitConfig.global_multiplier !== 1.0}
                                                    <span class="text-xs text-blue-600 dark:text-blue-400 ml-2">(→ {Math.floor(rule.requests * rateLimitConfig.global_multiplier)}/{rule.window_seconds}s)</span>
                                                {/if}
                                            </div>
                                            <span class="inline-block px-2 py-1 text-xs rounded-full {getGroupColor(rule.group)}">{rule.group}</span>
                                            <select bind:value={rule.algorithm} class="input input-sm" disabled={rateLimitConfig.bypass_rate_limit}>
                                                <option value="sliding_window">Sliding</option><option value="token_bucket">Token</option><option value="fixed_window">Fixed</option>
                                            </select>
                                            <label class="flex items-center gap-2 cursor-pointer">
                                                <input type="checkbox" bind:checked={rule.enabled} class="rounded text-blue-600" disabled={rateLimitConfig.bypass_rate_limit} />
                                                <span class="text-xs font-medium">{rule.enabled ? 'Enabled' : 'Disabled'}</span>
                                            </label>
                                            <button onclick={() => removeRule(index)} class="text-red-600 hover:text-red-800 dark:text-red-400 p-1" disabled={rateLimitConfig.bypass_rate_limit} title="Remove rule">
                                                <X class="w-4 h-4" />
                                            </button>
                                        </div>
                                    </div>
                                {/each}
                            </div>
                        </div>
                    {/if}
                </div>

                <!-- Current Usage -->
                {#if rateLimitUsage && Object.keys(rateLimitUsage).length > 0}
                    <div class="border border-neutral-200 dark:border-neutral-700 rounded-lg p-4">
                        <div class="flex justify-between items-center mb-3">
                            <h4 class="font-semibold text-fg-default dark:text-dark-fg-default">Current Usage</h4>
                            <button onclick={resetRateLimits} class="btn btn-sm btn-secondary">Reset All Counters</button>
                        </div>
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {#each Object.entries(rateLimitUsage) as [endpoint, usage]}
                                <div class="flex justify-between p-2 bg-neutral-50 dark:bg-neutral-900 rounded">
                                    <span class="text-sm font-mono text-fg-muted dark:text-dark-fg-muted">{endpoint}</span>
                                    <span class="text-sm font-semibold text-fg-default dark:text-dark-fg-default">{usage.count || usage.tokens_remaining || 0}</span>
                                </div>
                            {/each}
                        </div>
                    </div>
                {/if}
            </div>
            <div class="flex gap-3 justify-end mt-6">
                <button onclick={() => { showRateLimitModal = false; rateLimitUser = null; rateLimitConfig = null; }} class="btn btn-secondary" disabled={savingRateLimits}>Cancel</button>
                <button onclick={saveRateLimits} class="btn btn-primary flex items-center gap-2" disabled={savingRateLimits || loadingRateLimits}>
                    {#if savingRateLimits}<Spinner size="small" />Saving...{:else}Save Changes{/if}
                </button>
            </div>
        {/if}
    {/snippet}
</Modal>
{/if}

<!-- Create/Edit User Modal -->
{#if showUserModal}
<Modal open={showUserModal} title={editingUser ? 'Edit User' : 'Create New User'} onClose={() => showUserModal = false} size="sm">
    {#snippet children()}
        <form autocomplete="off" onsubmit={(e) => { e.preventDefault(); saveUser(); }}>
            <div class="space-y-4">
                <div>
                    <label for="user-form-username" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Username <span class="text-red-500">*</span></label>
                    <input id="user-form-username" type="text" bind:value={userForm.username} class="form-input-standard" placeholder="johndoe"
                        disabled={savingUser} autocomplete="username" autocorrect="off" autocapitalize="off" spellcheck="false" />
                </div>
                <div>
                    <label for="user-form-email" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Email</label>
                    <input id="user-form-email" type="email" bind:value={userForm.email} class="form-input-standard" placeholder="john@example.com"
                        disabled={savingUser} autocomplete="email" autocorrect="off" autocapitalize="off" spellcheck="false" />
                </div>
                <div>
                    <label for="user-form-password" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        Password {!editingUser ? '* ' : ''}{#if editingUser}<span class="text-xs text-neutral-500">(leave empty to keep current)</span>{/if}
                    </label>
                    <input id="user-form-password" type="password" bind:value={userForm.password} class="form-input-standard"
                        placeholder={editingUser ? 'Enter new password' : 'Enter password'} disabled={savingUser} autocomplete="new-password" />
                </div>
                <div>
                    <label for="user-form-role" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Role</label>
                    <select id="user-form-role" bind:value={userForm.role} class="form-select-standard" disabled={savingUser}>
                        <option value="user">User</option><option value="admin">Admin</option>
                    </select>
                </div>
                <div>
                    <label class="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" bind:checked={userForm.is_active} class="rounded text-blue-600 focus:ring-blue-500" disabled={savingUser} />
                        <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Active User</span>
                    </label>
                </div>
            </div>
            <div class="flex justify-end gap-2 mt-6">
                <button type="button" onclick={() => showUserModal = false} class="btn btn-outline" disabled={savingUser}>Cancel</button>
                <button type="submit" class="btn btn-primary flex items-center gap-2" disabled={savingUser}>
                    {#if savingUser}<Spinner size="small" />Saving...{:else}{editingUser ? 'Update User' : 'Create User'}{/if}
                </button>
            </div>
        </form>
    {/snippet}
</Modal>
{/if}
