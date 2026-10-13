import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { user, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { fakeDeleteUserResponse, fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { deleteUserApiV1AdminUsersUserIdDelete } from '#lib/api/index.ts';
import DeleteUserModal from '#components/admin/users/DeleteUserModal.svelte';

function renderModal() {
    const onClose = vi.fn();
    renderWithQueryClient(DeleteUserModal, {
        user: { ...fakeUserResponse(), user_id: 'u-1', username: 'alice' },
        onClose,
    });
    return { onClose };
}

describe('DeleteUserModal', () => {
    beforeEach(() => {
        mockApi(deleteUserApiV1AdminUsersUserIdDelete).ok(fakeDeleteUserResponse());
    });

    it('shows username in confirmation message', () => {
        renderModal();
        expect(screen.getByText('alice')).toBeInTheDocument();
        expect(screen.getByText(/Are you sure you want to delete user/)).toBeInTheDocument();
    });

    it('shows the cascade checkbox with what it deletes', () => {
        renderModal();
        expect(screen.getByRole('checkbox', { name: 'Cascade' })).toHaveAccessibleDescription(
            "Also deletes the user's executions, scripts and other data",
        );
    });

    it('warns about deleting the data only once cascade is checked', async () => {
        renderModal();
        expect(screen.queryByText(/permanently delete all data/)).not.toBeInTheDocument();
        await user.click(screen.getByRole('checkbox', { name: 'Cascade' }));
        expect(screen.getByText(/permanently delete all data/)).toBeInTheDocument();
    });

    it.each([false, true])('deletes the user with cascade=%s and closes', async (cascade) => {
        const { onClose } = renderModal();
        if (cascade) await user.click(screen.getByRole('checkbox', { name: 'Cascade' }));
        await user.click(screen.getByRole('button', { name: 'Delete User' }));

        await waitFor(() =>
            expect(vi.mocked(deleteUserApiV1AdminUsersUserIdDelete)).toHaveBeenCalledWith(
                expect.objectContaining({ path: { user_id: 'u-1' }, query: { cascade } }),
            ),
        );
        await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    });

    it('shows Deleting... and disables both buttons while the delete runs', async () => {
        mockApi(deleteUserApiV1AdminUsersUserIdDelete).mock.mockImplementation(() => new Promise(() => {}));
        renderModal();
        await user.click(screen.getByRole('button', { name: 'Delete User' }));

        expect(await screen.findByText('Deleting...')).toBeInTheDocument();
        expect(screen.getByText('Cancel')).toBeDisabled();
        expect(screen.getByRole('button', { name: /Deleting/ })).toBeDisabled();
    });

    it('calls onClose when Cancel button clicked', async () => {
        const { onClose } = renderModal();
        await user.click(screen.getByText('Cancel'));
        expect(onClose).toHaveBeenCalledOnce();
        expect(vi.mocked(deleteUserApiV1AdminUsersUserIdDelete)).not.toHaveBeenCalled();
    });
});
