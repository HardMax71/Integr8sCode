<script>
    import { onMount } from 'svelte';
    import { api } from '../../lib/api';
    import { addNotification } from '../../stores/notifications';
    import AdminLayout from './AdminLayout.svelte';
    
    let users = [];
    let loading = false;
    let selectedUser = null;
    
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
            addNotification(`Failed to load users: ${error.message}`, 'error');
            users = [];
        } finally {
            loading = false;
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
</script>

<AdminLayout path="/admin/users">
    <div class="container mx-auto px-4 pb-8">
        <div class="flex justify-between items-center mb-6">
            <h1 class="text-3xl font-bold text-fg-default dark:text-dark-fg-default">User Management</h1>
            
            <button
                on:click={loadUsers}
                class="btn btn-primary flex items-center gap-2"
                disabled={loading}
            >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" class:animate-spin={loading}>
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Refresh
            </button>
        </div>
        
        <div class="card">
            <div class="p-6">
                <h3 class="text-lg font-semibold text-fg-default dark:text-dark-fg-default mb-4">
                    Users ({users.length})
                </h3>
                
                <div class="overflow-x-auto">
                    <table class="w-full divide-y divide-border-default dark:divide-dark-border-default">
                        <thead class="bg-neutral-50 dark:bg-neutral-900">
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Username</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Email</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Role</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Created</th>
                                <th class="px-4 py-3 text-left text-xs font-medium text-fg-muted dark:text-dark-fg-muted uppercase tracking-wider">Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {#if loading}
                                <tr>
                                    <td colspan="5" class="px-4 py-8 text-center text-fg-muted dark:text-dark-fg-muted">
                                        Loading users...
                                    </td>
                                </tr>
                            {:else if users.length === 0}
                                <tr>
                                    <td colspan="5" class="px-4 py-8 text-center text-fg-muted dark:text-dark-fg-muted">
                                        No users found
                                    </td>
                                </tr>
                            {:else}
                                {#each users as user}
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
                                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {user.active ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'}">
                                                {user.active ? 'Active' : 'Inactive'}
                                            </span>
                                        </td>
                                    </tr>
                                {/each}
                            {/if}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</AdminLayout>