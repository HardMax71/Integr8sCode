import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { user, createMockUser, createMockUsers } from '$test/test-utils';
import UsersTable from '$components/admin/users/UsersTable.svelte';

vi.mock('$lib/formatters', () => ({
  formatTimestamp: vi.fn((ts: string) => `formatted:${ts}`),
}));

function renderTable(props: Record<string, unknown> = {}) {
  const onEdit = vi.fn();
  const onRateLimits = vi.fn();
  const onDelete = vi.fn();
  const result = render(UsersTable, {
    props: { users: [], loading: false, onEdit, onRateLimits, onDelete, ...props },
  });
  return { ...result, onEdit, onRateLimits, onDelete };
}

describe('UsersTable', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows loading text when loading', () => {
    renderTable({ loading: true });
    expect(screen.getByText('Loading users...')).toBeInTheDocument();
  });

  it('shows empty state when no users', () => {
    renderTable({ users: [] });
    expect(screen.getByText('No users found matching filters')).toBeInTheDocument();
  });

  it('does not show loading or empty state when users exist', () => {
    renderTable({ users: createMockUsers(2) });
    expect(screen.queryByText('Loading users...')).not.toBeInTheDocument();
    expect(screen.queryByText('No users found matching filters')).not.toBeInTheDocument();
  });

  it('renders desktop table headers', () => {
    renderTable({ users: [createMockUser()] });
    expect(screen.getByText('Username')).toBeInTheDocument();
    expect(screen.getByText('Email')).toBeInTheDocument();
    expect(screen.getByText('Role')).toBeInTheDocument();
    expect(screen.getByText('Created')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Actions')).toBeInTheDocument();
  });

  it('renders one row per user in desktop table', () => {
    const users = createMockUsers(3);
    const { container } = renderTable({ users });
    const rows = container.querySelectorAll('tbody tr');
    expect(rows).toHaveLength(3);
  });

  it('renders mobile cards for each user', () => {
    const users = createMockUsers(2);
    const { container } = renderTable({ users });
    // Mobile view: block lg:hidden div with cards
    const mobileCards = container.querySelectorAll('.block.lg\\:hidden > div');
    expect(mobileCards).toHaveLength(2);
  });

  it('displays username and email', () => {
    renderTable({ users: [createMockUser({ username: 'alice', email: 'alice@test.com' })] });
    const aliceTexts = screen.getAllByText('alice');
    expect(aliceTexts.length).toBeGreaterThanOrEqual(1);
    const emailTexts = screen.getAllByText('alice@test.com');
    expect(emailTexts.length).toBeGreaterThanOrEqual(1);
  });

  it('displays role badge', () => {
    renderTable({ users: [createMockUser({ role: 'admin' })] });
    const badges = screen.getAllByText('admin');
    expect(badges.length).toBeGreaterThanOrEqual(1);
  });

  it.each([
    [true, 'Active'],
    [false, 'Inactive'],
  ] as const)('displays %s status for is_active=%s', (isActive, label) => {
    renderTable({ users: [createMockUser({ is_active: isActive })] });
    const texts = screen.getAllByText(label);
    expect(texts.length).toBeGreaterThanOrEqual(1);
  });

  it('displays dash for missing email in desktop table', () => {
    renderTable({ users: [createMockUser({ email: '' })] });
    const dashes = screen.getAllByText('-');
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  it('displays "No email" for missing email in mobile card', () => {
    renderTable({ users: [createMockUser({ email: '' })] });
    expect(screen.getByText('No email')).toBeInTheDocument();
  });

  it.each([
    ['Edit User', 'onEdit'],
    ['Manage Rate Limits', 'onRateLimits'],
    ['Delete User', 'onDelete'],
  ] as const)('calls %s callback when button clicked', async (title, callbackKey) => {
    const mockUser = createMockUser();
    const result = renderTable({ users: [mockUser] });
    const btns = screen.getAllByTitle(title);
    await user.click(btns[0]!);
    expect(result[callbackKey]).toHaveBeenCalledWith(mockUser);
  });

  it('formats created_at timestamp', () => {
    renderTable({ users: [createMockUser({ created_at: '2024-01-15T10:30:00Z' })] });
    const formatted = screen.getAllByText('formatted:2024-01-15T10:30:00Z');
    expect(formatted.length).toBeGreaterThanOrEqual(1);
  });
});
