<script lang="ts">
    import type { UserResponse } from '$lib/api';
    import Modal from '$components/Modal.svelte';
    import Spinner from '$components/Spinner.svelte';

    interface UserForm {
        username: string;
        email: string;
        password: string;
        role: string;
        is_active: boolean;
    }

    interface Props {
        open: boolean;
        editingUser: UserResponse | null;
        form: UserForm;
        saving: boolean;
        onClose: () => void;
        onSave: () => void;
    }

    let {
        open,
        editingUser,
        form = $bindable({ username: '', email: '', password: '', role: 'user', is_active: true }),
        saving,
        onClose,
        onSave
    }: Props = $props();

    function handleSubmit(e: Event): void {
        e.preventDefault();
        onSave();
    }
</script>

<Modal {open} title={editingUser ? 'Edit User' : 'Create New User'} {onClose} size="sm">
    {#snippet children()}
        <form autocomplete="off" onsubmit={handleSubmit}>
            <div class="space-y-4">
                <div>
                    <label for="user-form-username" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                        Username <span class="text-red-500">*</span>
                    </label>
                    <input
                        id="user-form-username"
                        type="text"
                        bind:value={form.username}
                        class="form-input-standard"
                        placeholder="johndoe"
                        disabled={saving}
                        autocomplete="username"
                        autocorrect="off"
                        autocapitalize="off"
                        spellcheck="false"
                    />
                </div>
                <div>
                    <label for="user-form-email" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Email</label>
                    <input
                        id="user-form-email"
                        type="email"
                        bind:value={form.email}
                        class="form-input-standard"
                        placeholder="john@example.com"
                        disabled={saving}
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
                            <span class="text-xs text-neutral-500">(leave empty to keep current)</span>
                        {/if}
                    </label>
                    <input
                        id="user-form-password"
                        type="password"
                        bind:value={form.password}
                        class="form-input-standard"
                        placeholder={editingUser ? 'Enter new password' : 'Enter password'}
                        disabled={saving}
                        autocomplete="new-password"
                    />
                </div>
                <div>
                    <label for="user-form-role" class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">Role</label>
                    <select id="user-form-role" bind:value={form.role} class="form-select-standard" disabled={saving}>
                        <option value="user">User</option>
                        <option value="admin">Admin</option>
                    </select>
                </div>
                <div>
                    <label class="flex items-center gap-2 cursor-pointer">
                        <input
                            type="checkbox"
                            bind:checked={form.is_active}
                            class="rounded text-blue-600 focus:ring-blue-500"
                            disabled={saving}
                        />
                        <span class="text-sm font-medium text-fg-default dark:text-dark-fg-default">Active User</span>
                    </label>
                </div>
            </div>
            <div class="flex justify-end gap-2 mt-6">
                <button type="button" onclick={onClose} class="btn btn-outline" disabled={saving}>Cancel</button>
                <button type="submit" class="btn btn-primary flex items-center gap-2" disabled={saving}>
                    {#if saving}
                        <Spinner size="small" />Saving...
                    {:else}
                        {editingUser ? 'Update User' : 'Create User'}
                    {/if}
                </button>
            </div>
        </form>
    {/snippet}
</Modal>
