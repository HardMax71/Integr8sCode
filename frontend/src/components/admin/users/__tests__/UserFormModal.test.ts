import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { proxy } from 'svelte/internal/client';
import { user, createMockUser } from '$test/test-utils';
import UserFormModal from '$components/admin/users/UserFormModal.svelte';

vi.mock('$components/Spinner.svelte', async () => {
  const utils = await import('$test/test-utils');
  return { default: utils.createMockNamedComponents({ default: '<span data-testid="spinner">...</span>' }).default };
});

function renderModal(overrides: Record<string, unknown> = {}) {
  const onClose = vi.fn();
  const onSave = vi.fn();
  const result = render(UserFormModal, {
    props: {
      open: true,
      editingUser: null,
      form: proxy({ username: '', email: '', password: '', role: 'user', is_active: true }),
      saving: false,
      onClose,
      onSave,
      ...overrides,
    },
  });
  return { ...result, onClose, onSave };
}

describe('UserFormModal', () => {
  beforeEach(() => vi.clearAllMocks());

  it('does not render when open is false', () => {
    renderModal({ open: false });
    expect(screen.queryByText('Create New User')).not.toBeInTheDocument();
  });

  it.each([
    ['creating', null, 'Create New User'],
    ['editing', 'mock', 'Edit User'],
  ] as const)('shows correct title when %s', (_label, editingUser, title) => {
    renderModal({ editingUser: editingUser === 'mock' ? createMockUser() : null });
    expect(screen.getByText(title)).toBeInTheDocument();
  });

  it.each([/Username/, 'Email', /Password/, 'Role'])('renders %s field', (label) => {
    renderModal();
    expect(screen.getByLabelText(label)).toBeInTheDocument();
  });

  it.each([
    ['creating', null, 'Create User', false],
    ['editing', 'mock', 'Update User', true],
  ] as const)('when %s: button="%s", password hint=%s', (_label, editingUser, buttonText, showsHint) => {
    renderModal({ editingUser: editingUser === 'mock' ? createMockUser() : null });
    expect(screen.getByText(buttonText)).toBeInTheDocument();
    if (showsHint) expect(screen.getByText('(leave empty to keep current)')).toBeInTheDocument();
    else expect(screen.queryByText('(leave empty to keep current)')).not.toBeInTheDocument();
  });

  it('shows Saving... text when saving', () => {
    renderModal({ saving: true });
    expect(screen.getByText('Saving...')).toBeInTheDocument();
  });

  it.each(['Cancel', 'Saving...'])('disables %s button when saving', (text) => {
    renderModal({ saving: true });
    const el = screen.getByText(text);
    const btn = el.closest('button') ?? el;
    expect(btn).toBeDisabled();
  });

  it('calls onClose when Cancel is clicked', async () => {
    const { onClose } = renderModal();
    await user.click(screen.getByText('Cancel'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('calls onSave on form submit', async () => {
    const { onSave } = renderModal();
    await user.click(screen.getByText('Create User'));
    expect(onSave).toHaveBeenCalledOnce();
  });
});
