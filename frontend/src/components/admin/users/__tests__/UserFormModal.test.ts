import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { user, createMockUser } from '#test/test-utils.ts';
import UserFormModal from '#components/admin/users/UserFormModal.svelte';

vi.mock('#components/Spinner.svelte', async () => {
    const utils = await import('#test/test-utils.ts');
    return { default: utils.createMockNamedComponents({ default: '<span data-testid="spinner">...</span>' }).default };
});

function renderModal(overrides: Record<string, unknown> = {}) {
    const onClose = vi.fn();
    const onCreate = vi.fn();
    const onEdit = vi.fn();
    const result = render(UserFormModal, {
        props: { open: true, editingUser: null, saving: false, onClose, onCreate, onEdit, ...overrides },
    });
    return { ...result, onClose, onCreate, onEdit };
}

const field = (label: RegExp | string) => screen.getByLabelText(label);

async function fill(values: { username?: string; email?: string; password?: string }) {
    for (const [label, value] of [
        [/Username/, values.username],
        [/^Email/, values.email],
        [/Password/, values.password],
    ] as const) {
        if (value === undefined) continue;
        await user.clear(field(label));
        if (value) await user.type(field(label), value);
    }
}

describe('UserFormModal', () => {
    beforeEach(() => vi.clearAllMocks());

    it('does not render when open is false', () => {
        renderModal({ open: false });
        expect(screen.queryByText('Create New User')).not.toBeInTheDocument();
    });

    it.each([
        ['creating', null, 'Create New User', 'Create User', false],
        ['editing', 'mock', 'Edit User', 'Update User', true],
    ] as const)('when %s: title, button and password hint', (_label, editingUser, title, buttonText, showsHint) => {
        renderModal({ editingUser: editingUser === 'mock' ? createMockUser() : null });
        expect(screen.getByRole('dialog', { name: title })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: buttonText })).toBeInTheDocument();
        if (showsHint)
            expect(field(/Password/)).toHaveAccessibleDescription('Leave empty to keep the current password');
        else expect(screen.queryByText('Leave empty to keep the current password')).not.toBeInTheDocument();
    });

    it.each([/Username/, /^Email/, /Password/, 'Role', 'Is Active'])('renders the %s field', (label) => {
        renderModal();
        expect(field(label)).toBeInTheDocument();
    });

    it('starts a new user from the API defaults', () => {
        renderModal();
        expect(field('Role')).toHaveValue('user');
        expect(field('Is Active')).toBeChecked();
    });

    it('creates a user with what was typed', async () => {
        const { onCreate } = renderModal();
        await fill({ username: 'newuser', email: 'new@example.com', password: 'password123' });
        await user.click(screen.getByRole('button', { name: 'Create User' }));

        await waitFor(() =>
            expect(onCreate).toHaveBeenCalledWith({
                username: 'newuser',
                email: 'new@example.com',
                password: 'password123',
                role: 'user',
                is_active: true,
            }),
        );
    });

    it.each([
        ['an empty username', { username: '', email: 'a@b.co', password: 'password123' }, /Username/, 'Required'],
        [
            'an invalid email',
            { username: 'u', email: 'nope', password: 'password123' },
            /^Email/,
            'Must be a valid email',
        ],
        [
            'a short password',
            { username: 'u', email: 'a@b.co', password: 'short' },
            /Password/,
            'Must be at least 8 characters',
        ],
    ])('refuses to create with %s', async (_name, values, label, message) => {
        const { onCreate } = renderModal();
        await fill(values);
        await user.click(screen.getByRole('button', { name: 'Create User' }));

        await waitFor(() => expect(field(label)).toHaveAccessibleDescription(message));
        expect(onCreate).not.toHaveBeenCalled();
    });

    it('edits a user without sending the password when it stays empty', async () => {
        const editingUser = createMockUser({ user_id: 'u-7', username: 'alice', email: 'alice@example.com' });
        const { onEdit } = renderModal({ editingUser });
        expect(field(/Username/)).toHaveValue('alice');

        await fill({ username: 'alice2' });
        await user.click(screen.getByRole('button', { name: 'Update User' }));

        await waitFor(() =>
            expect(onEdit).toHaveBeenCalledWith('u-7', {
                username: 'alice2',
                email: 'alice@example.com',
                role: editingUser.role,
                is_active: editingUser.is_active,
            }),
        );
    });

    it('sends a new password when one is typed', async () => {
        const { onEdit } = renderModal({ editingUser: createMockUser({ user_id: 'u-8' }) });
        await fill({ password: 'newpassword' });
        await user.click(screen.getByRole('button', { name: 'Update User' }));

        await waitFor(() =>
            expect(onEdit).toHaveBeenCalledWith('u-8', expect.objectContaining({ password: 'newpassword' })),
        );
    });

    it('keeps requiring an email when editing, since every user has one', async () => {
        const { onEdit } = renderModal({ editingUser: createMockUser() });
        await fill({ email: '' });
        await user.click(screen.getByRole('button', { name: 'Update User' }));

        await waitFor(() => expect(field(/^Email/)).toHaveAccessibleDescription('Must be a valid email'));
        expect(onEdit).not.toHaveBeenCalled();
    });

    it('still checks a new password against the API rule when editing', async () => {
        const { onEdit } = renderModal({ editingUser: createMockUser() });
        await fill({ password: 'short' });
        await user.click(screen.getByRole('button', { name: 'Update User' }));

        await waitFor(() =>
            expect(field(/Password/)).toHaveAccessibleDescription(
                'Leave empty to keep the current password Must be at least 8 characters',
            ),
        );
        expect(onEdit).not.toHaveBeenCalled();
    });

    it('disables the fields and buttons while saving', () => {
        renderModal({ saving: true });
        expect(screen.getByText('Saving...').closest('button')).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
        expect(field(/Username/)).toBeDisabled();
    });

    it('calls onClose when Cancel is clicked', async () => {
        const { onClose } = renderModal();
        await user.click(screen.getByRole('button', { name: 'Cancel' }));
        expect(onClose).toHaveBeenCalledOnce();
    });
});
