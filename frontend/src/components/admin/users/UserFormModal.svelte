<script lang="ts">
    import { untrack } from 'svelte';
    import * as z from 'zod/mini';
    import { Control, Field, FieldErrors, Label } from 'formsnap';
    import { UserRole, zUserCreate, type UserCreate, type UserResponse, type UserUpdate } from '#lib/api/index.ts';
    import { apiForm, filled, optionalText } from '#lib/forms.ts';
    import { formatEnumLabel } from '#lib/formatters.ts';
    import Modal from '#components/Modal.svelte';
    import Spinner from '#components/Spinner.svelte';

    interface Props {
        open: boolean;
        editingUser: UserResponse | null;
        saving: boolean;
        onClose: () => void;
        onCreate: (body: UserCreate) => void;
        onEdit: (userId: string, body: UserUpdate) => void;
    }

    let { open, editingUser, saving, onClose, onCreate, onEdit }: Props = $props();

    // The page mounts the dialog per open, so the user it edits never changes
    const editing = untrack(() => editingUser);

    const { username, email, password, role, is_active } = zUserCreate.shape;
    // An edited user may keep the current password; a new one needs one
    const schema = z.object({
        username: filled(username),
        email,
        password: editing ? optionalText(password) : password,
        role,
        is_active,
    });

    const form = apiForm(
        schema,
        {
            onUpdate: ({ form: submitted }) => {
                if (!submitted.valid) return;
                const data = submitted.data;
                if (!editing) {
                    onCreate(data);
                    return;
                }
                onEdit(editing.user_id, {
                    username: data.username,
                    email: data.email,
                    role: data.role,
                    is_active: data.is_active,
                    ...(data.password ? { password: data.password } : {}),
                });
            },
        },
        editing
            ? {
                  username: editing.username,
                  email: editing.email,
                  password: '',
                  role: editing.role,
                  is_active: editing.is_active,
              }
            : undefined,
    );
    const { form: formData, constraints, enhance } = form;
</script>

{#snippet textField(
    name: 'username' | 'email' | 'password',
    label: string,
    type: string,
    placeholder: string,
    autocomplete: HTMLInputElement['autocomplete'],
)}
    <Field {form} {name}>
        <Control id="user-form-{name}">
            {#snippet children({ props })}
                <Label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1">
                    {label}
                    {#if name !== 'password' || !editing}
                        <span class="text-red-500">*</span>
                    {/if}
                    {#if name === 'password' && editing}
                        <span class="text-xs text-neutral-500">(leave empty to keep current)</span>
                    {/if}
                </Label>
                <input
                    {...props}
                    {...$constraints[name]}
                    {type}
                    {placeholder}
                    {autocomplete}
                    bind:value={$formData[name]}
                    class="form-input-standard"
                    disabled={saving}
                    autocapitalize="off"
                    spellcheck="false"
                />
            {/snippet}
        </Control>
        <FieldErrors class="mt-1 text-sm text-red-600 dark:text-red-400" />
    </Field>
{/snippet}

<Modal {open} title={editing ? 'Edit User' : 'Create New User'} {onClose} size="sm">
    {#snippet children()}
        <form method="post" use:enhance novalidate autocomplete="off">
            <div class="space-y-4">
                {@render textField('username', 'Username', 'text', 'johndoe', 'username')}
                {@render textField('email', 'Email', 'email', 'john@example.com', 'email')}
                {@render textField(
                    'password',
                    'Password',
                    'password',
                    editing ? 'Enter new password' : 'Enter password',
                    'new-password',
                )}
                <Field {form} name="role">
                    <Control id="user-form-role">
                        {#snippet children({ props })}
                            <Label class="block text-sm font-medium text-fg-muted dark:text-dark-fg-muted mb-1"
                                >Role</Label
                            >
                            <select
                                {...props}
                                bind:value={$formData.role}
                                class="form-select-standard"
                                disabled={saving}
                            >
                                {#each Object.values(UserRole) as option (option)}
                                    <option value={option}>{formatEnumLabel(option)}</option>
                                {/each}
                            </select>
                        {/snippet}
                    </Control>
                </Field>
                <Field {form} name="is_active">
                    <Control>
                        {#snippet children({ props })}
                            <div class="flex items-center gap-2">
                                <input
                                    {...props}
                                    type="checkbox"
                                    bind:checked={$formData.is_active}
                                    disabled={saving}
                                />
                                <Label
                                    class="text-sm font-medium text-fg-default dark:text-dark-fg-default cursor-pointer"
                                    >Active User</Label
                                >
                            </div>
                        {/snippet}
                    </Control>
                </Field>
            </div>
            <div class="flex justify-end gap-2 mt-6">
                <button type="button" onclick={onClose} class="btn btn-secondary-outline" disabled={saving}
                    >Cancel</button
                >
                <button type="submit" class="btn btn-primary flex items-center gap-2" disabled={saving}>
                    {#if saving}
                        <Spinner size="small" />Saving...
                    {:else}
                        {editing ? 'Update User' : 'Create User'}
                    {/if}
                </button>
            </div>
        </form>
    {/snippet}
</Modal>
