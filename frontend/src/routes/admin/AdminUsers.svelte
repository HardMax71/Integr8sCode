<script>
    import { onMount } from 'svelte';
    import { api } from '../../lib/api';
    import { addToast } from '../../stores/toastStore';
    import AdminLayout from './AdminLayout.svelte';
    import Spinner from '../../components/Spinner.svelte';
    
    let users = [];
    let loading = false;
    let selectedUser = null;
    let showDeleteModal = false;
    let showRateLimitModal = false;
    let userToDelete = null;
    let rateLimitUser = null;
    let rateLimitConfig = null;
    let rateLimitUsage = null;
    let cascadeDelete = true;
    let deletingUser = false;
    let loadingRateLimits = false;
    let savingRateLimits = false;
    
    // Pagination
    let currentPage = 1;
    let pageSize = 10;
    let totalUsers = 0;
    
    // Search and filters
    let searchQuery = '';
    let roleFilter = 'all';
    let statusFilter = 'all';
    let showAdvancedFilters = false;
    let advancedFilters = {
        bypassRateLimit: 'all',
        hasCustomLimits: 'all',
        globalMultiplier: 'all'
    };
    
    // User creation/editing
    let showUserModal = false;
    let editingUser = null;
    let userForm = {
        username: '',
        email: '',
        password: '',
        role: 'user',
        is_active: true
    };
    let savingUser = false;
    
    // Computed values
    $: totalPages = Math.ceil(filteredUsers.length / pageSize);
    $: paginatedUsers = filteredUsers.slice((currentPage - 1) * pageSize, currentPage * pageSize);
    $: filteredUsers = filterUsers(users, searchQuery, roleFilter, statusFilter, advancedFilters);
    
    onMount(() => {
        loadUsers();
    });
    
    async function loadUsers() {
        loading = true;
        try {
            const response = await api.get('/api/v1/admin/users/');
            users = Array.isArray(response) ? response : response?.users || [];
        } catch (error) {
            console.error('Failed to load users:', error);
            addToast(`Failed to load users: ${error.message}`, 'error');
            users = [];
        } finally {
            loading = false;
        }
    }
    
    async function deleteUser() {
        if (!userToDelete) return;
        
        deletingUser = true;
        try {
            const response = await api.delete(
                `/api/v1/admin/users/${userToDelete.user_id}?cascade=${cascadeDelete}`
            );
            
            addToast(response.message, 'success');
            
            if (response.deleted_counts) {
                const counts = Object.entries(response.deleted_counts)
                    .filter(([key, value]) => value > 0)
                    .map(([key, value]) => `${key}: ${value}`)
                    .join(', ');
                if (counts) {
                    addToast(`Deleted data: ${counts}`, 'info');
                }
            }
            
            await loadUsers();
            showDeleteModal = false;
            userToDelete = null;
        } catch (error) {
            console.error('Failed to delete user:', error);
            addToast(`Failed to delete user: ${error.message}`, 'error');
        } finally {
            deletingUser = false;
        }
    }
    
    async function openRateLimitModal(user) {
        rateLimitUser = user;
        showRateLimitModal = true;
        loadingRateLimits = true;
        
        try {
            const response = await api.get(`/api/v1/admin/users/${user.user_id}/rate-limits`);
            rateLimitConfig = response.rate_limit_config || {
                user_id: user.user_id,
                rules: [],
                global_multiplier: 1.0,
                bypass_rate_limit: false,
                notes: ''
            };
            rateLimitUsage = response.current_usage || {};
        } catch (error) {
            console.error('Failed to load rate limits:', error);
            addToast(`Failed to load rate limits: ${error.message}`, 'error');
        } finally {
            loadingRateLimits = false;
        }
    }
    
    async function saveRateLimits() {
        if (!rateLimitUser || !rateLimitConfig) return;
        
        savingRateLimits = true;
        try {
            console.log('Sending rate limit config:', rateLimitConfig);
            await api.put(
                `/api/v1/admin/users/${rateLimitUser.user_id}/rate-limits`,
                rateLimitConfig
            );
            addToast('Rate limits updated successfully', 'success');
            showRateLimitModal = false;
        } catch (error) {
            console.error('Failed to save rate limits:', error);
            await handleValidationError(error, 'Failed to save rate limits');
        } finally {
            savingRateLimits = false;
        }
    }
    
    async function resetRateLimits() {
        if (!rateLimitUser) return;
        
        try {
            const response = await api.post(
                `/api/v1/admin/users/${rateLimitUser.user_id}/rate-limits/reset`
            );
            addToast(response.message, 'success');
            rateLimitUsage = {};
        } catch (error) {
            console.error('Failed to reset rate limits:', error);
            addToast(`Failed to reset rate limits: ${error.message}`, 'error');
        }
    }
    
    function formatDate(dateString) {
        const date = new Date(dateString);
        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = date.getFullYear();
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${day}/${month}/${year} ${hours}:${minutes}`;
    }
    
    // Make default rules reactive to global_multiplier changes
    $: defaultRulesWithEffective = getDefaultRulesWithMultiplier(rateLimitConfig?.global_multiplier);
    
    function getDefaultRulesWithMultiplier(multiplier) {
        // These are the default rules from the backend
        const rules = [
            {
                endpoint_pattern: '^/api/v1/execute',
                group: 'execution',
                requests: 10,
                window_seconds: 60,
                algorithm: 'sliding_window',
                priority: 10
            },
            {
                endpoint_pattern: '^/api/v1/admin/.*',
                group: 'admin',
                requests: 100,
                window_seconds: 60,
                algorithm: 'sliding_window',
                priority: 5
            },
            {
                endpoint_pattern: '^/api/v1/events/.*',
                group: 'sse',
                requests: 5,
                window_seconds: 60,
                algorithm: 'sliding_window',
                priority: 8
            },
            {
                endpoint_pattern: '^/api/v1/ws',
                group: 'websocket',
                requests: 5,
                window_seconds: 60,
                algorithm: 'sliding_window',
                priority: 8
            },
            {
                endpoint_pattern: '^/api/v1/auth/.*',
                group: 'auth',
                requests: 20,
                window_seconds: 60,
                algorithm: 'sliding_window',
                priority: 7
            },
            {
                endpoint_pattern: '^/api/v1/.*',
                group: 'api',
                requests: 60,
                window_seconds: 60,
                algorithm: 'sliding_window',
                priority: 1
            }
        ];
        
        // Apply global multiplier to show effective limits
        const effectiveMultiplier = multiplier || 1.0;
        return rules.map(rule => ({
            ...rule,
            effective_requests: Math.floor(rule.requests * effectiveMultiplier)
        }));
    }
    
    function getGroupColor(group) {
        const colors = {
            execution: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
            admin: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
            sse: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
            websocket: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
            auth: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
            api: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200',
            public: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200'
        };
        return colors[group] || colors.api;
    }
    
    // Define endpoint group patterns for automatic detection
    const endpointGroupPatterns = [
        { pattern: /\/execute/i, group: 'execution' },
        { pattern: /\/admin\//i, group: 'admin' },
        { pattern: /\/events\//i, group: 'sse' },
        { pattern: /\/ws/i, group: 'websocket' },
        { pattern: /\/auth\//i, group: 'auth' },
        { pattern: /\/dlq/i, group: 'api' },
        { pattern: /\/health/i, group: 'public' },
        { pattern: /\/metrics/i, group: 'api' },
        { pattern: /\/kafka/i, group: 'api' },
        { pattern: /\/replay/i, group: 'api' },
        { pattern: /\/saga/i, group: 'api' },
        { pattern: /\/projections/i, group: 'api' },
        { pattern: /\/notifications/i, group: 'api' },
        { pattern: /\/saved-scripts/i, group: 'api' },
        { pattern: /\/user-settings/i, group: 'api' },
        { pattern: /\/alerts\//i, group: 'api' },
    ];
    
    function detectGroupFromEndpoint(endpoint) {
        // Remove regex anchors and wildcards if present
        const cleanEndpoint = endpoint.replace(/^\^?/, '').replace(/\$?/, '').replace(/\.\*/g, '');
        
        // Check each pattern
        for (const { pattern, group } of endpointGroupPatterns) {
            if (pattern.test(cleanEndpoint)) {
                return group;
            }
        }
        
        // Default to 'api' if no match
        return 'api';
    }
    
    function handleEndpointChange(rule) {
        // Automatically set group based on endpoint pattern
        if (rule.endpoint_pattern) {
            rule.group = detectGroupFromEndpoint(rule.endpoint_pattern);
        }
    }
    
    function addNewRule() {
        if (!rateLimitConfig.rules) {
            rateLimitConfig.rules = [];
        }
        rateLimitConfig.rules = [...rateLimitConfig.rules, {
            endpoint_pattern: '',
            group: 'api',
            requests: 60,
            window_seconds: 60,
            burst_multiplier: 1.5,
            algorithm: 'sliding_window',
            priority: 0,
            enabled: true
        }];
    }
    
    function removeRule(index) {
        rateLimitConfig.rules = rateLimitConfig.rules.filter((_, i) => i !== index);
    }
    
    function filterUsers(userList, search, role, status, advanced) {
        let filtered = [...userList];
        
        // Search filter (username, email, user_id)
        if (search) {
            const searchLower = search.toLowerCase();
            filtered = filtered.filter(user => 
                user.username?.toLowerCase().includes(searchLower) ||
                user.email?.toLowerCase().includes(searchLower) ||
                user.user_id?.toLowerCase().includes(searchLower)
            );
        }
        
        // Role filter
        if (role !== 'all') {
            filtered = filtered.filter(user => user.role === role);
        }
        
        // Status filter
        if (status === 'active') {
            filtered = filtered.filter(user => !user.is_disabled);
        } else if (status === 'disabled') {
            filtered = filtered.filter(user => user.is_disabled);
        }
        
        // Advanced filters - these would need rate limit data loaded for each user
        // For now, we'll add placeholders that can be connected when the data is available
        if (advanced.bypassRateLimit === 'yes') {
            filtered = filtered.filter(user => user.bypass_rate_limit === true);
        } else if (advanced.bypassRateLimit === 'no') {
            filtered = filtered.filter(user => user.bypass_rate_limit !== true);
        }
        
        if (advanced.hasCustomLimits === 'yes') {
            filtered = filtered.filter(user => user.has_custom_limits === true);
        } else if (advanced.hasCustomLimits === 'no') {
            filtered = filtered.filter(user => user.has_custom_limits !== true);
        }
        
        if (advanced.globalMultiplier === 'custom') {
            filtered = filtered.filter(user => user.global_multiplier && user.global_multiplier !== 1.0);
        } else if (advanced.globalMultiplier === 'default') {
            filtered = filtered.filter(user => !user.global_multiplier || user.global_multiplier === 1.0);
        }
        
        return filtered;
    }
    
    function openCreateUserModal() {
        editingUser = null;
        userForm = {
            username: '',
            email: '',
            password: '',
            role: 'user',
            is_active: true
        };
        showUserModal = true;
    }
    
    function openEditUserModal(user) {
        editingUser = user;
        userForm = {
            username: user.username,
            email: user.email || '',
            password: '', // Don't prefill password
            role: user.role,
            is_active: !user.is_disabled
        };
        showUserModal = true;
    }
    
    async function saveUser() {
        if (!userForm.username) {
            addToast('Username is required', 'error');
            return;
        }
        
        savingUser = true;
        try {
            if (editingUser) {
                // Update existing user
                const updateData = {
                    username: userForm.username,
                    email: userForm.email || null,
                    role: userForm.role,
                    is_active: userForm.is_active
                };
                
                // Only include password if it was changed
                if (userForm.password) {
                    updateData.password = userForm.password;
                }
                
                await api.put(`/api/v1/admin/users/${editingUser.user_id}`, updateData);
                addToast('User updated successfully', 'success');
            } else {
                // Create new user
                if (!userForm.password) {
                    addToast('Password is required for new users', 'error');
                    return;
                }
                
                await api.post('/api/v1/admin/users/', {
                    username: userForm.username,
                    email: userForm.email || null,
                    password: userForm.password,
                    role: userForm.role,
                    is_active: userForm.is_active
                });
                addToast('User created successfully', 'success');
            }
            
            showUserModal = false;
            await loadUsers();
        } catch (error) {
            console.error('Failed to save user:', error);
            await handleValidationError(error, 'Failed to save user');
        } finally {
            savingUser = false;
        }
    }
    
    function changePage(page) {
        if (page >= 1 && page <= totalPages) {
            currentPage = page;
        }
    }
    
    function resetFilters() {
        searchQuery = '';
        roleFilter = 'all';
        statusFilter = 'all';
        advancedFilters = {
            bypassRateLimit: 'all',
            hasCustomLimits: 'all',
            globalMultiplier: 'all'
        };
        currentPage = 1;
    }
    
    // Reset to first page when filters change
    $: searchQuery, roleFilter, statusFilter, currentPage = 1;
    
    // Helper function to extract validation error messages
    async function handleValidationError(error, defaultMessage) {
        if (error.response && error.response.status === 422) {
            try {
                const errorData = await error.response.json();
                console.error('Validation errors:', errorData);
                
                // Extract all validation messages
                if (errorData.detail && Array.isArray(errorData.detail)) {
                    const messages = errorData.detail.map(err => {
                        const field = err.loc && err.loc.length > 1 ? err.loc[err.loc.length - 1] : 'field';
                        return `${field}: ${err.msg}`;
                    });
                    addToast(`Validation failed:\n${messages.join('\n')}`, 'error');
                } else if (errorData.detail && typeof errorData.detail === 'string') {
                    addToast(`Validation failed: ${errorData.detail}`, 'error');
                } else {
                    addToast(`Validation failed: ${JSON.stringify(errorData)}`, 'error');
                }
            } catch (e) {
                addToast(`${defaultMessage}: ${error.message}`, 'error');
            }
        } else {
            addToast(`${defaultMessage}: ${error.message}`, 'error');
        }
    }
</script>

<AdminLayout path="/admin/users">
    <div class="container mx-auto px-2 sm:px-4 pb-8">
        <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
            <h1 class="text-2xl sm:text-3xl font-bold text-fg-default dark:text-dark-fg-default">User Management</h1>
            
            <div class="flex gap-2 w-full sm:w-auto">
                <button
                    on:click={openCreateUserModal}
                    class="btn btn-primary flex items-center gap-2 flex-1 sm:flex-initial justify-center"
                >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                    </svg>
                    Create User
                </button>
                
                <button
                    on:click={loadUsers}
                    class="btn btn-outline flex items-center gap-2 flex-1 sm:flex-initial justify-center"
                    disabled={loading}
                >
                    {#if loading}
                        <Spinner size="small" />
                    {:else}
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                    {/if}
                    Refresh
                </button>
            </div>
        </div>
        
        <!-- Search and Filters -->
        <div class="card mb-4">
            <div class="p-3 sm:p-4">
                <div class="flex flex-col lg:flex-row gap-3 lg:gap-4 lg:items-end">
                    <!-- Search input -->
                    <div class="w-full lg:flex-1 lg:max-w-md">
                        <label for="user-search" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                            Search
                        </label>
                        <input
                            id="user-search"
                            type="text"
                            bind:value={searchQuery}
                            placeholder="Search by username, email, or ID..."
                            class="input w-full"
                            autocomplete="off"
                            autocorrect="off"
                            autocapitalize="off"
                            spellcheck="false"
                        />
                    </div>

                    <!-- Role filter -->
                    <div class="w-full sm:w-auto sm:min-w-[140px]">
                        <label for="role-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                            Role
                        </label>
                        <select id="role-filter" bind:value={roleFilter} class="form-select-standard w-full">
                            <option value="all">All Roles</option>
                            <option value="user">User</option>
                            <option value="admin">Admin</option>
                        </select>
                    </div>

                    <!-- Status filter -->
                    <div class="w-full sm:w-auto sm:min-w-[140px]">
                        <label for="status-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                            Status
                        </label>
                        <select id="status-filter" bind:value={statusFilter} class="form-select-standard w-full">
                            <option value="all">All Status</option>
                            <option value="active">Active</option>
                            <option value="disabled">Disabled</option>
                        </select>
                    </div>
                    
                    <!-- Advanced filters toggle -->
                    <button
                        on:click={() => showAdvancedFilters = !showAdvancedFilters}
                        class="btn btn-outline flex items-center gap-2 w-full sm:w-auto justify-center"
                    >
                        <svg class="w-4 h-4 transition-transform {showAdvancedFilters ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                        </svg>
                        Advanced
                    </button>
                    
                    <!-- Reset button -->
                    <button
                        on:click={resetFilters}
                        class="btn btn-outline w-full sm:w-auto"
                        disabled={!searchQuery && roleFilter === 'all' && statusFilter === 'all' && 
                                 advancedFilters.bypassRateLimit === 'all' && 
                                 advancedFilters.hasCustomLimits === 'all' && 
                                 advancedFilters.globalMultiplier === 'all'}
                    >
                        Reset
                    </button>
                </div>
                
                <!-- Advanced Filters Section -->
                {#if showAdvancedFilters}
                    <div class="mt-4 pt-4 border-t border-neutral-200 dark:border-neutral-700">
                        <h4 class="text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-3">Rate Limit Filters</h4>
                        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                            <div>
                                <label for="bypass-rate-limit-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    Bypass Rate Limit
                                </label>
                                <select id="bypass-rate-limit-filter" bind:value={advancedFilters.bypassRateLimit} class="form-select-standard w-full">
                                    <option value="all">All</option>
                                    <option value="yes">Yes (Bypassed)</option>
                                    <option value="no">No (Limited)</option>
                                </select>
                            </div>

                            <div>
                                <label for="custom-limits-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    Custom Limits
                                </label>
                                <select id="custom-limits-filter" bind:value={advancedFilters.hasCustomLimits} class="form-select-standard w-full">
                                    <option value="all">All</option>
                                    <option value="yes">Has Custom</option>
                                    <option value="no">Default Only</option>
                                </select>
                            </div>

                            <div>
                                <label for="global-multiplier-filter" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                                    Global Multiplier
                                </label>
                                <select id="global-multiplier-filter" bind:value={advancedFilters.globalMultiplier} class="form-select-standard w-full">
                                    <option value="all">All</option>
                                    <option value="custom">Custom (≠ 1.0)</option>
                                    <option value="default">Default (= 1.0)</option>
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
                    <div class="py-8 text-center text-fg-muted dark:text-dark-fg-muted">
                        Loading users...
                    </div>
                {:else if filteredUsers.length === 0}
                    <div class="py-8 text-center text-fg-muted dark:text-dark-fg-muted">
                        No users found matching filters
                    </div>
                {:else}
                    <!-- Mobile Card View -->
                    <div class="block lg:hidden">
                        {#each paginatedUsers as user}
                            <div class="p-4 border-b border-border-default dark:border-dark-border-default hover:bg-neutral-50 dark:hover:bg-neutral-800">
                                <div class="flex justify-between items-start mb-3">
                                    <div class="flex-1 min-w-0">
                                        <div class="font-medium text-fg-default dark:text-dark-fg-default">
                                            {user.username}
                                        </div>
                                        <div class="text-sm text-fg-muted dark:text-dark-fg-muted mt-1">
                                            {user.email || 'No email'}
                                        </div>
                                    </div>
                                    <div class="flex gap-2 items-center">
                                        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium {user.role === 'admin' ? 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'}">
                                            {user.role}
                                        </span>
                                        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium {user.is_active ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'}">
                                            {user.is_active ? 'Active' : 'Inactive'}
                                        </span>
                                    </div>
                                </div>
                                
                                <div class="text-xs text-fg-muted dark:text-dark-fg-muted mb-3">
                                    Created: {formatDate(user.created_at)}
                                </div>
                                
                                <div class="flex gap-2">
                                    <button
                                        on:click={() => openEditUserModal(user)}
                                        class="flex-1 btn btn-sm btn-outline flex items-center justify-center gap-1"
                                    >
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                        </svg>
                                        Edit
                                    </button>
                                    
                                    <button
                                        on:click={() => openRateLimitModal(user)}
                                        class="flex-1 btn btn-sm btn-outline flex items-center justify-center gap-1"
                                    >
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                                        </svg>
                                        Limits
                                    </button>
                                    
                                    <button
                                        on:click={() => {
                                            userToDelete = user;
                                            showDeleteModal = true;
                                        }}
                                        class="btn btn-sm btn-danger flex items-center justify-center gap-1"
                                    >
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                        </svg>
                                        Delete
                                    </button>
                                </div>
                            </div>
                        {/each}
                    </div>
                    
                    <!-- Desktop Table View -->
                    <div class="hidden lg:block overflow-x-auto">
                        <table class="w-full divide-y divide-border-default dark:divide-dark-border-default">
                            <thead class="bg-neutral-50 dark:bg-neutral-900">
                                <tr>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Username</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Email</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Role</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Created</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Status</th>
                                    <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {#each paginatedUsers as user}
                                    <tr class="hover:bg-neutral-50 dark:hover:bg-neutral-800">
                                        <td class="px-4 py-3 whitespace-nowrap text-sm text-fg-default dark:text-dark-fg-default font-medium">
                                            {user.username}
                                        </td>
                                        <td class="px-4 py-3 whitespace-nowrap text-sm text-fg-default dark:text-dark-fg-default">
                                            {user.email || '-'}
                                        </td>
                                        <td class="px-4 py-3 whitespace-nowrap text-sm">
                                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {user.role === 'admin' ? 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'}">
                                                {user.role}
                                            </span>
                                        </td>
                                        <td class="px-4 py-3 whitespace-nowrap text-sm text-fg-default dark:text-dark-fg-default">
                                            {formatDate(user.created_at)}
                                        </td>
                                        <td class="px-4 py-3 whitespace-nowrap text-sm">
                                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {user.is_active ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'}">
                                                {user.is_active ? 'Active' : 'Inactive'}
                                            </span>
                                        </td>
                                        <td class="px-4 py-3 whitespace-nowrap text-sm">
                                            <div class="flex gap-2">
                                                <button
                                                    on:click={() => openEditUserModal(user)}
                                                    class="text-green-600 hover:text-green-800 dark:text-green-400 dark:hover:text-green-300"
                                                    title="Edit User"
                                                >
                                                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                                    </svg>
                                                </button>
                                                
                                                <button
                                                    on:click={() => openRateLimitModal(user)}
                                                    class="text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
                                                    title="Manage Rate Limits"
                                                >
                                                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                                                    </svg>
                                                </button>
                                                <button
                                                    on:click={() => {
                                                        userToDelete = user;
                                                        showDeleteModal = true;
                                                    }}
                                                    class="text-red-600 hover:text-red-800 dark:text-red-400 dark:hover:text-red-300"
                                                    title="Delete User"
                                                >
                                                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                                    </svg>
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                {/each}
                            </tbody>
                        </table>
                    </div>
                {/if}
                
                <!-- Pagination -->
                {#if totalPages > 1}
                    <div class="mt-4 border-t border-border-default dark:border-dark-border-default pt-4">
                        <div class="flex flex-col gap-3">
                            <!-- Simple pagination controls -->
                            <div class="flex items-center justify-center gap-2">
                                <!-- Previous button -->
                                <button
                                    on:click={() => changePage(currentPage - 1)}
                                    disabled={currentPage === 1}
                                    class="px-3 py-1 rounded border border-border-default dark:border-dark-border-default 
                                           hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed
                                           text-sm"
                                >
                                    Previous
                                </button>
                                
                                <!-- Current page indicator -->
                                <div class="px-3 py-1 text-sm">
                                    Page <span class="font-medium">{currentPage}</span> of <span class="font-medium">{totalPages}</span>
                                </div>
                                
                                <!-- Next button -->
                                <button
                                    on:click={() => changePage(currentPage + 1)}
                                    disabled={currentPage === totalPages}
                                    class="px-3 py-1 rounded border border-border-default dark:border-dark-border-default 
                                           hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed
                                           text-sm"
                                >
                                    Next
                                </button>
                            </div>
                            
                            <!-- Page size selector -->
                            <div class="flex items-center justify-center gap-2">
                                <label for="users-page-size" class="text-xs text-fg-muted dark:text-dark-fg-muted">Show:</label>
                                <select
                                    id="users-page-size"
                                    bind:value={pageSize}
                                    on:change={() => currentPage = 1}
                                    class="text-sm px-2 py-1 rounded border border-border-default dark:border-dark-border-default
                                           bg-bg-default dark:bg-dark-bg-default text-fg-default dark:text-dark-fg-default"
                                >
                                    <option value={5}>5</option>
                                    <option value={10}>10</option>
                                    <option value={20}>20</option>
                                    <option value={50}>50</option>
                                </select>
                                <span class="text-xs text-fg-muted dark:text-dark-fg-muted">per page</span>
                            </div>
                            
                            <!-- Info text -->
                            <div class="text-xs sm:text-sm text-fg-muted dark:text-dark-fg-muted ml-auto">
                                Showing {(currentPage - 1) * pageSize + 1} - {Math.min(currentPage * pageSize, filteredUsers.length)} of {filteredUsers.length} users
                            </div>
                        </div>
                    </div>
                {/if}
            </div>
        </div>
    </div>
    
    <!-- Delete User Modal -->
    {#if showDeleteModal && userToDelete}
        <div class="fixed inset-0 bg-black/50 flex items-center justify-center p-3 sm:p-4 z-50">
            <div class="bg-white dark:bg-gray-800 rounded-lg p-4 sm:p-6 max-w-md w-full">
                <h3 class="text-xl font-bold mb-4 text-fg-default dark:text-dark-fg-default">
                    Delete User
                </h3>
                
                <p class="mb-4 text-fg-default dark:text-dark-fg-default">
                    Are you sure you want to delete user <strong>{userToDelete.username}</strong>?
                </p>
                
                <div class="mb-4">
                    <label class="flex items-center gap-2">
                        <input
                            type="checkbox"
                            bind:checked={cascadeDelete}
                            class="rounded border-border-default dark:border-dark-border-default"
                        />
                        <span class="text-sm text-fg-default dark:text-dark-fg-default">
                            Delete all user data (executions, scripts, etc.)
                        </span>
                    </label>
                </div>
                
                {#if cascadeDelete}
                    <div class="mb-4 p-3 bg-yellow-100 dark:bg-yellow-900 rounded-lg">
                        <p class="text-sm text-yellow-800 dark:text-yellow-200">
                            <strong>Warning:</strong> This will permanently delete all data associated with this user.
                        </p>
                    </div>
                {/if}
                
                <div class="flex gap-3 justify-end">
                    <button
                        on:click={() => {
                            showDeleteModal = false;
                            userToDelete = null;
                        }}
                        class="btn btn-secondary"
                        disabled={deletingUser}
                    >
                        Cancel
                    </button>
                    <button
                        on:click={deleteUser}
                        class="btn btn-danger flex items-center gap-2"
                        disabled={deletingUser}
                    >
                        {#if deletingUser}
                            <Spinner size="small" />
                            Deleting...
                        {:else}
                            Delete User
                        {/if}
                    </button>
                </div>
            </div>
        </div>
    {/if}
    
    <!-- Rate Limit Modal -->
    {#if showRateLimitModal && rateLimitUser}
        <div class="fixed inset-0 bg-black/50 flex items-center justify-center p-3 sm:p-4 z-50">
            <div class="bg-white dark:bg-gray-800 rounded-lg p-4 sm:p-6 max-w-4xl w-full max-h-[95vh] sm:max-h-[90vh] overflow-y-auto">
                <h3 class="text-xl font-bold mb-4 text-fg-default dark:text-dark-fg-default">
                    Rate Limits for {rateLimitUser.username}
                </h3>
                
                {#if loadingRateLimits}
                    <div class="flex justify-center py-8">
                        <Spinner />
                    </div>
                {:else if rateLimitConfig}
                    <div class="space-y-4">
                        <!-- Quick Settings -->
                        <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-gray-50 dark:bg-gray-900">
                            <div class="flex items-center justify-between mb-3">
                                <h4 class="font-semibold text-fg-default dark:text-dark-fg-default">
                                    Quick Settings
                                </h4>
                                <label class="flex items-center gap-2">
                                    <input
                                        type="checkbox"
                                        bind:checked={rateLimitConfig.bypass_rate_limit}
                                        class="rounded"
                                    />
                                    <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">
                                        Bypass all rate limits
                                    </span>
                                </label>
                            </div>
                            
                            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div>
                                    <label for="global-multiplier" class="block text-sm font-medium mb-1 text-fg-default dark:text-dark-fg-default">
                                        Global Multiplier
                                    </label>
                                    <input
                                        id="global-multiplier"
                                        type="number"
                                        bind:value={rateLimitConfig.global_multiplier}
                                        min="0.01"
                                        step="0.1"
                                        class="input w-full"
                                        disabled={rateLimitConfig.bypass_rate_limit}
                                    />
                                    <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                        Multiplies all limits (1.0 = default, 2.0 = double)
                                    </p>
                                </div>
                                <div>
                                    <label for="admin-notes" class="block text-sm font-medium mb-1 text-fg-default dark:text-dark-fg-default">
                                        Admin Notes
                                    </label>
                                    <textarea
                                        id="admin-notes"
                                        bind:value={rateLimitConfig.notes}
                                        rows="2"
                                        class="input w-full text-sm"
                                        placeholder="Notes about this user's rate limits..."
                                    />
                                </div>
                            </div>
                        </div>
                        
                        <!-- Endpoint-Specific Limits -->
                        <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
                            <div class="flex justify-between items-center mb-4">
                                <h4 class="font-semibold text-fg-default dark:text-dark-fg-default">
                                    Endpoint Rate Limits
                                </h4>
                                <button
                                    on:click={() => addNewRule()}
                                    class="btn btn-sm btn-primary flex items-center gap-1"
                                    disabled={rateLimitConfig.bypass_rate_limit}
                                >
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                                    </svg>
                                    Add Rule
                                </button>
                            </div>
                            
                            <!-- Default Rules (Global) -->
                            <div class="mb-4">
                                <h5 class="text-xs sm:text-sm font-medium text-gray-600 dark:text-gray-400 mb-2">Default Global Rules</h5>
                                <div class="space-y-2">
                                    {#each defaultRulesWithEffective || [] as rule}
                                        <div class="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-900 rounded-lg">
                                            <div class="flex-1 grid grid-cols-2 lg:grid-cols-4 gap-2 lg:gap-4 items-center">
                                                <div>
                                                    <span class="text-xs text-gray-500 dark:text-gray-400">Endpoint</span>
                                                    <p class="text-sm font-mono text-fg-default dark:text-dark-fg-default">{rule.endpoint_pattern}</p>
                                                </div>
                                                <div>
                                                    <span class="text-xs text-gray-500 dark:text-gray-400">Limit</span>
                                                    <p class="text-sm text-fg-default dark:text-dark-fg-default">
                                                        {#if rateLimitConfig?.global_multiplier !== 1.0}
                                                            <span class="line-through text-gray-400">{rule.requests}</span>
                                                            <span class="font-semibold text-blue-600 dark:text-blue-400">{rule.effective_requests}</span>
                                                        {:else}
                                                            {rule.requests}
                                                        {/if}
                                                        req / {rule.window_seconds}s
                                                    </p>
                                                </div>
                                                <div>
                                                    <span class="text-xs text-gray-500 dark:text-gray-400">Group</span>
                                                    <span class="inline-block px-2 py-1 text-xs rounded-full {getGroupColor(rule.group)}">
                                                        {rule.group}
                                                    </span>
                                                </div>
                                                <div>
                                                    <span class="text-xs text-gray-500 dark:text-gray-400">Algorithm</span>
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
                                    <h5 class="text-xs sm:text-sm font-medium text-gray-600 dark:text-gray-400 mb-2">User-Specific Overrides</h5>
                                    <div class="space-y-2">
                                        {#each rateLimitConfig.rules as rule, index}
                                            <div class="p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
                                                <div class="flex flex-col lg:flex-row items-start lg:items-center gap-3">
                                                    <!-- Endpoint Pattern -->
                                                    <div class="w-full lg:flex-1 lg:min-w-[200px]">
                                                        <input
                                                            type="text"
                                                            bind:value={rule.endpoint_pattern}
                                                            on:input={() => handleEndpointChange(rule)}
                                                            placeholder="Endpoint pattern (e.g., /api/v1/auth/verify)"
                                                            class="input input-sm w-full"
                                                            disabled={rateLimitConfig.bypass_rate_limit}
                                                        />
                                                    </div>
                                                    
                                                    <!-- Rate Limit -->
                                                    <div class="flex items-center gap-1 flex-wrap">
                                                        <input
                                                            type="number"
                                                            bind:value={rule.requests}
                                                            placeholder="600"
                                                            min="1"
                                                            class="input input-sm w-16"
                                                            disabled={rateLimitConfig.bypass_rate_limit}
                                                        />
                                                        <span class="text-xs text-gray-500">/</span>
                                                        <input
                                                            type="number"
                                                            bind:value={rule.window_seconds}
                                                            placeholder="60"
                                                            min="1"
                                                            class="input input-sm w-16"
                                                            disabled={rateLimitConfig.bypass_rate_limit}
                                                        />
                                                        <span class="text-xs text-gray-500">s</span>
                                                        {#if rateLimitConfig.global_multiplier !== 1.0}
                                                            <span class="text-xs text-blue-600 dark:text-blue-400 ml-2">
                                                                (→ {Math.floor(rule.requests * rateLimitConfig.global_multiplier)}/{rule.window_seconds}s)
                                                            </span>
                                                        {/if}
                                                    </div>
                                                    
                                                    <!-- Group Badge -->
                                                    <div>
                                                        <span class="inline-block px-2 py-1 text-xs rounded-full {getGroupColor(rule.group)}">
                                                            {rule.group}
                                                        </span>
                                                    </div>
                                                    
                                                    <!-- Algorithm -->
                                                    <div>
                                                        <select
                                                            bind:value={rule.algorithm}
                                                            class="input input-sm"
                                                            disabled={rateLimitConfig.bypass_rate_limit}
                                                        >
                                                            <option value="sliding_window">Sliding</option>
                                                            <option value="token_bucket">Token</option>
                                                            <option value="fixed_window">Fixed</option>
                                                        </select>
                                                    </div>
                                                    
                                                    <!-- Active Toggle -->
                                                    <label class="flex items-center gap-2 cursor-pointer">
                                                        <input
                                                            type="checkbox"
                                                            bind:checked={rule.enabled}
                                                            class="rounded text-blue-600 focus:ring-blue-500"
                                                            disabled={rateLimitConfig.bypass_rate_limit}
                                                        />
                                                        <span class="text-xs font-medium {rule.enabled ? 'text-fg-default dark:text-dark-fg-default' : 'text-gray-400 dark:text-gray-500'}">
                                                            {rule.enabled ? 'Enabled' : 'Disabled'}
                                                        </span>
                                                    </label>
                                                    
                                                    <!-- Delete Button -->
                                                    <button
                                                        on:click={() => removeRule(index)}
                                                        class="text-red-600 hover:text-red-800 dark:text-red-400 dark:hover:text-red-300 p-1"
                                                        disabled={rateLimitConfig.bypass_rate_limit}
                                                        title="Remove rule"
                                                    >
                                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                                                        </svg>
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
                            <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
                                <div class="flex justify-between items-center mb-3">
                                    <h4 class="font-semibold text-fg-default dark:text-dark-fg-default">
                                        Current Usage
                                    </h4>
                                    <button
                                        on:click={resetRateLimits}
                                        class="btn btn-sm btn-secondary"
                                    >
                                        Reset All Counters
                                    </button>
                                </div>
                                
                                <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                    {#each Object.entries(rateLimitUsage) as [endpoint, usage]}
                                        <div class="flex justify-between p-2 bg-gray-50 dark:bg-gray-900 rounded">
                                            <span class="text-sm font-mono text-fg-muted dark:text-dark-fg-muted">{endpoint}</span>
                                            <div class="text-sm text-fg-default dark:text-dark-fg-default">
                                                <span class="font-semibold">{usage.count || usage.tokens_remaining || 0}</span>
                                                {#if usage.algorithm}
                                                    <span class="text-xs text-gray-500 dark:text-gray-400 ml-1">({usage.algorithm})</span>
                                                {/if}
                                            </div>
                                        </div>
                                    {/each}
                                </div>
                            </div>
                        {/if}
                    </div>
                {/if}
                
                <div class="flex gap-3 justify-end mt-6">
                    <button
                        on:click={() => {
                            showRateLimitModal = false;
                            rateLimitUser = null;
                            rateLimitConfig = null;
                        }}
                        class="btn btn-secondary"
                        disabled={savingRateLimits}
                    >
                        Cancel
                    </button>
                    <button
                        on:click={saveRateLimits}
                        class="btn btn-primary flex items-center gap-2"
                        disabled={savingRateLimits || loadingRateLimits}
                    >
                        {#if savingRateLimits}
                            <Spinner size="small" />
                            Saving...
                        {:else}
                            Save Changes
                        {/if}
                    </button>
                </div>
            </div>
        </div>
    {/if}
    
    <!-- Create/Edit User Modal -->
    {#if showUserModal}
        <div class="fixed inset-0 bg-black/50 flex items-center justify-center p-3 sm:p-4 z-50">
            <div class="bg-bg-default dark:bg-dark-bg-default rounded-lg p-4 sm:p-6 max-w-md w-full max-h-[95vh] sm:max-h-[90vh] overflow-y-auto">
                <h2 class="text-xl font-bold mb-4 text-fg-default dark:text-dark-fg-default">
                    {editingUser ? 'Edit User' : 'Create New User'}
                </h2>
                
                <form autocomplete="off" on:submit|preventDefault={saveUser}>
                <div class="space-y-4">
                    <div>
                        <label for="user-form-username" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                            Username <span class="text-red-500">*</span>
                        </label>
                        <input
                            id="user-form-username"
                            type="text"
                            bind:value={userForm.username}
                            class="form-input-standard"
                            placeholder="johndoe"
                            disabled={savingUser}
                            autocomplete="username"
                            autocorrect="off"
                            autocapitalize="off"
                            spellcheck="false"
                        />
                    </div>

                    <div>
                        <label for="user-form-email" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                            Email
                        </label>
                        <input
                            id="user-form-email"
                            type="email"
                            bind:value={userForm.email}
                            class="form-input-standard"
                            placeholder="john@example.com"
                            disabled={savingUser}
                            autocomplete="email"
                            autocorrect="off"
                            autocapitalize="off"
                            spellcheck="false"
                        />
                    </div>

                    <div>
                        <label for="user-form-password" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                            Password {!editingUser ? '* ' : ''}
                            {#if editingUser}
                                <span class="text-xs text-gray-500">(leave empty to keep current)</span>
                            {/if}
                        </label>
                        <input
                            id="user-form-password"
                            type="password"
                            bind:value={userForm.password}
                            class="form-input-standard"
                            placeholder={editingUser ? 'Enter new password' : 'Enter password'}
                            disabled={savingUser}
                            autocomplete="new-password"
                            autocorrect="off"
                            autocapitalize="off"
                            spellcheck="false"
                        />
                    </div>

                    <div>
                        <label for="user-form-role" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                            Role
                        </label>
                        <select id="user-form-role" bind:value={userForm.role} class="form-select-standard" disabled={savingUser}>
                            <option value="user">User</option>
                            <option value="admin">Admin</option>
                        </select>
                    </div>
                    
                    <div>
                        <label class="flex items-center gap-2 cursor-pointer">
                            <input
                                type="checkbox"
                                bind:checked={userForm.is_active}
                                class="rounded text-blue-600 focus:ring-blue-500"
                                disabled={savingUser}
                            />
                            <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">
                                Active User
                            </span>
                        </label>
                    </div>
                </div>
                
                <div class="flex justify-end gap-2 mt-6">
                    <button
                        type="button"
                        on:click={() => showUserModal = false}
                        class="btn btn-outline"
                        disabled={savingUser}
                    >
                        Cancel
                    </button>
                    <button
                        type="submit"
                        class="btn btn-primary flex items-center gap-2"
                        disabled={savingUser}
                    >
                        {#if savingUser}
                            <Spinner size="small" />
                            Saving...
                        {:else}
                            {editingUser ? 'Update User' : 'Create User'}
                        {/if}
                    </button>
                </div>
                </form>
            </div>
        </div>
    {/if}
</AdminLayout>