import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import * as z from 'zod/mini';
import { user, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import {
    createUserApiV1AdminUsersPost,
    updateUserApiV1AdminUsersUserIdPut,
    zUserCreateWritable,
    type UserResponse,
} from '#lib/api/index.ts';
import UserFormModal from '#components/admin/users/UserFormModal.svelte';

const defaultRole = zUserCreateWritable.shape.role.parse(undefined);
const defaultIsActive = zUserCreateWritable.shape.is_active.parse(undefined);
const passwordMinLength = z.toJSONSchema(zUserCreateWritable.shape.password).minLength!;
const shortPassword = 'x'.repeat(passwordMinLength - 1);

function renderModal(mode: { kind: 'create' } | { kind: 'edit'; user: UserResponse } = { kind: 'create' }) {
    const onClose = vi.fn();
    renderWithQueryClient(UserFormModal, { mode, onClose });
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
        mockApi(createUserApiV1AdminUsersPost).ok(fakeUserResponse());
        mockApi(updateUserApiV1AdminUsersUserIdPut).ok(fakeUserResponse());
    });

    it.each([
        ['creating', 'create', 'Create New User', 'Create User', false],
        ['editing', 'edit', 'Edit User', 'Update User', true],
    ] as const)('when %s: title, button and password hint', (_label, kind, title, buttonText, showsHint) => {
        renderModal(kind === 'edit' ? { kind, user: fakeUserResponse() } : { kind });
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
        expect(field('Role')).toHaveValue(defaultRole);
        expect((field('Is Active') as HTMLInputElement).checked).toBe(defaultIsActive);
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
                        role: defaultRole,
                        is_active: defaultIsActive,
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
            { username: 'u', email: 'a@b.co', password: shortPassword },
            /Password/,
            `Must be at least ${passwordMinLength} characters`,
        ],
    ])('refuses to create with %s', async (_name, values, label, message) => {
        renderModal();
        await fill(values);
        await user.click(screen.getByRole('button', { name: 'Create User' }));

        await waitFor(() => expect(field(label)).toHaveAccessibleDescription(message));
        expect(createUser()).not.toHaveBeenCalled();
    });

    it('edits a user without sending the password when it stays empty, then closes', async () => {
        const editingUser = { ...fakeUserResponse(), user_id: 'u-7', username: 'alice', email: 'alice@example.com' };
        const { onClose } = renderModal({ kind: 'edit', user: editingUser });
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
        renderModal({
            kind: 'edit',
            user: { ...fakeUserResponse(), user_id: 'u-8', username: 'bob', email: 'bob@example.com' },
        });
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
        renderModal({ kind: 'edit', user: fakeUserResponse() });
        await fill({ email: '' });
        await user.click(screen.getByRole('button', { name: 'Update User' }));

        await waitFor(() => expect(field(/^Email/)).toHaveAccessibleDescription('Must be a valid email'));
        expect(updateUser()).not.toHaveBeenCalled();
    });

    it('still checks a new password against the API rule when editing', async () => {
        renderModal({ kind: 'edit', user: fakeUserResponse() });
        await fill({ password: shortPassword });
        await user.click(screen.getByRole('button', { name: 'Update User' }));

        await waitFor(() =>
            expect(field(/Password/)).toHaveAccessibleDescription(
                `Leave empty to keep the current password Must be at least ${passwordMinLength} characters`,
            ),
        );
        expect(updateUser()).not.toHaveBeenCalled();
    });

    it('disables the fields and buttons while saving', async () => {
        mockApi(createUserApiV1AdminUsersPost).mock.mockImplementation(() => new Promise(() => {}));
        renderModal();
        await fill({ username: 'newuser', email: 'new@example.com', password: 'password123' });
        await user.click(screen.getByRole('button', { name: 'Create User' }));

        expect(await screen.findByRole('button', { name: /Saving/ })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
        expect(field(/Username/)).toBeDisabled();
    });

    it('calls onClose when Cancel is clicked', async () => {
        const { onClose } = renderModal();
        await user.click(screen.getByRole('button', { name: 'Cancel' }));
        expect(onClose).toHaveBeenCalledOnce();
    });
});
