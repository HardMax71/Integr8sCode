import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { user, createMockUser, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import {
    createUserApiV1AdminUsersPost,
    updateUserApiV1AdminUsersUserIdPut,
    type UserResponse,
} from '#lib/api/index.ts';
import UserFormModal from '#components/admin/users/UserFormModal.svelte';

vi.mock('#components/Spinner.svelte', async () => {
    const utils = await import('#test/test-utils.ts');
    return { default: utils.createMockNamedComponents({ default: '<span data-testid="spinner">...</span>' }).default };
});

function renderModal(editingUser: UserResponse | null = null) {
    const onClose = vi.fn();
    renderWithQueryClient(UserFormModal, { editingUser, onClose });
    return { onClose };
}

const createUser = () => vi.mocked(createUserApiV1AdminUsersPost);
const updateUser = () => vi.mocked(updateUserApiV1AdminUsersUserIdPut);

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
    beforeEach(() => {
        vi.clearAllMocks();
        mockApi(createUserApiV1AdminUsersPost).ok(createMockUser());
        mockApi(updateUserApiV1AdminUsersUserIdPut).ok(createMockUser());
    });

    it.each([
        ['creating', null, 'Create New User', 'Create User', false],
        ['editing', 'mock', 'Edit User', 'Update User', true],
    ] as const)('when %s: title, button and password hint', (_label, editingUser, title, buttonText, showsHint) => {
        renderModal(editingUser === 'mock' ? createMockUser() : null);
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

    it('creates a user with what was typed, then closes', async () => {
        const { onClose } = renderModal();
        await fill({ username: 'newuser', email: 'new@example.com', password: 'password123' });
        await user.click(screen.getByRole('button', { name: 'Create User' }));

        await waitFor(() =>
            expect(createUser()).toHaveBeenCalledWith(
                expect.objectContaining({
                    body: {
                        username: 'newuser',
                        email: 'new@example.com',
                        password: 'password123',
                        role: 'user',
                        is_active: true,
                    },
                }),
            ),
        );
        await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
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
        renderModal();
        await fill(values);
        await user.click(screen.getByRole('button', { name: 'Create User' }));

        await waitFor(() => expect(field(label)).toHaveAccessibleDescription(message));
        expect(createUser()).not.toHaveBeenCalled();
    });

    it('edits a user without sending the password when it stays empty, then closes', async () => {
        const editingUser = createMockUser({ user_id: 'u-7', username: 'alice', email: 'alice@example.com' });
        const { onClose } = renderModal(editingUser);
        expect(field(/Username/)).toHaveValue('alice');

        await fill({ username: 'alice2' });
        await user.click(screen.getByRole('button', { name: 'Update User' }));

        await waitFor(() =>
            expect(updateUser()).toHaveBeenCalledWith(
                expect.objectContaining({
                    path: { user_id: 'u-7' },
                    body: {
                        username: 'alice2',
                        email: 'alice@example.com',
                        role: editingUser.role,
                        is_active: editingUser.is_active,
                    },
                }),
            ),
        );
        await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    });

    it('sends a new password when one is typed', async () => {
        renderModal(createMockUser({ user_id: 'u-8' }));
        await fill({ password: 'newpassword' });
        await user.click(screen.getByRole('button', { name: 'Update User' }));

        await waitFor(() =>
            expect(updateUser()).toHaveBeenCalledWith(
                expect.objectContaining({
                    path: { user_id: 'u-8' },
                    body: expect.objectContaining({ password: 'newpassword' }),
                }),
            ),
        );
    });

    it('keeps requiring an email when editing, since every user has one', async () => {
        renderModal(createMockUser());
        await fill({ email: '' });
        await user.click(screen.getByRole('button', { name: 'Update User' }));

        await waitFor(() => expect(field(/^Email/)).toHaveAccessibleDescription('Must be a valid email'));
        expect(updateUser()).not.toHaveBeenCalled();
    });

    it('still checks a new password against the API rule when editing', async () => {
        renderModal(createMockUser());
        await fill({ password: 'short' });
        await user.click(screen.getByRole('button', { name: 'Update User' }));

        await waitFor(() =>
            expect(field(/Password/)).toHaveAccessibleDescription(
                'Leave empty to keep the current password Must be at least 8 characters',
            ),
        );
        expect(updateUser()).not.toHaveBeenCalled();
    });

    it('disables the fields and buttons while saving', async () => {
        mockApi(createUserApiV1AdminUsersPost).mock.mockImplementation(() => new Promise(() => {}));
        renderModal();
        await fill({ username: 'newuser', email: 'new@example.com', password: 'password123' });
        await user.click(screen.getByRole('button', { name: 'Create User' }));

        expect((await screen.findByText('Saving...')).closest('button')).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
        expect(field(/Username/)).toBeDisabled();
    });

    it('calls onClose when Cancel is clicked', async () => {
        const { onClose } = renderModal();
        await user.click(screen.getByRole('button', { name: 'Cancel' }));
        expect(onClose).toHaveBeenCalledOnce();
    });
});
