import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user, createMockUser } from '$test/test-utils';
import DeleteUserModal from '$components/admin/users/DeleteUserModal.svelte';

vi.mock('$components/Spinner.svelte', async () => {
  const utils = await import('$test/test-utils');
  return { default: utils.createMockNamedComponents({ default: '<span data-testid="spinner">...</span>' }).default };
});

function renderModal(overrides: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const onDelete = vi.fn();
  const onCascadeChange = vi.fn();
  const result = render(DeleteUserModal, {
    props: {
      open: true,
      user: createMockUser({ username: 'alice' }),
      cascadeDelete: false,
      deleting: false,
      onClose,
      onDelete,
      onCascadeChange,
      ...overrides,
    },
  });
  return { ...result, onClose, onDelete, onCascadeChange };
}

describe('DeleteUserModal', () => {
  beforeEach(() => vi.clearAllMocks());

  it.each([
    ['open is false', { open: false }],
    ['user is null', { user: null }],
  ] as const)('does not render content when %s', (_label, overrides) => {
    renderModal(overrides);
    expect(screen.queryByText(/Are you sure/)).not.toBeInTheDocument();
  });

  it('shows username in confirmation message', () => {
    renderModal();
    expect(screen.getByText('alice')).toBeInTheDocument();
    expect(screen.getByText(/Are you sure you want to delete user/)).toBeInTheDocument();
  });

  it('shows cascade delete checkbox', () => {
    renderModal();
    expect(screen.getByText(/Delete all user data/)).toBeInTheDocument();
  });

  it.each([
    [false, false],
    [true, true],
  ] as const)('cascade warning visibility when cascadeDelete=%s', (cascadeDelete, visible) => {
    renderModal({ cascadeDelete });
    if (visible) expect(screen.getByText(/permanently delete all data/)).toBeInTheDocument();
    else expect(screen.queryByText(/permanently delete all data/)).not.toBeInTheDocument();
  });

  it('shows Delete User button text when not deleting', () => {
    renderModal({ deleting: false });
    const deleteBtn = screen.getByRole('button', { name: 'Delete User' });
    expect(deleteBtn).toBeInTheDocument();
  });

  it('shows Deleting... text when deleting', () => {
    renderModal({ deleting: true });
    expect(screen.getByText('Deleting...')).toBeInTheDocument();
  });

  it('disables buttons when deleting', () => {
    renderModal({ deleting: true });
    expect(screen.getByText('Cancel')).toBeDisabled();
    expect(screen.getByText('Deleting...').closest('button')).toBeDisabled();
  });

  it('calls onDelete when Delete User button clicked', async () => {
    const { onDelete } = renderModal();
    await user.click(screen.getByRole('button', { name: 'Delete User' }));
    expect(onDelete).toHaveBeenCalledOnce();
  });

  it('calls onClose when Cancel button clicked', async () => {
    const { onClose } = renderModal();
    await user.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalledOnce();
  });

});
