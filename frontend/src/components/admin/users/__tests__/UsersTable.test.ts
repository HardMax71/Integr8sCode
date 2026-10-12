import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import { user } from '#test/test-utils.ts';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { UserRole } from '#lib/api/index.ts';
import UsersTable from '#components/admin/users/UsersTable.svelte';

vi.mock('#lib/formatters.ts', async (importOriginal) => ({
    ...(await importOriginal<typeof import('#lib/formatters.ts')>()),
    formatTimestamp: vi.fn((ts: string) => `formatted:${ts}`),
}));

function renderTable(props: Record<string, unknown> = {}) {
    const onEdit = vi.fn();
    const onRateLimits = vi.fn();
    const onDelete = vi.fn();
    const result = render(UsersTable, {
        props: {
            users: [],
            rowCount: 0,
            pagination: { pageIndex: 0, pageSize: 10 },
            loading: false,
            onEdit,
            onRateLimits,
            onDelete,
            ...props,
        },
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
        renderTable({ users: Array.from({ length: 2 }, () => fakeUserResponse()) });
        expect(screen.queryByText('Loading users...')).not.toBeInTheDocument();
        expect(screen.queryByText('No users found matching filters')).not.toBeInTheDocument();
    });

    it.each(['Username', 'Email', 'Role', 'Created At', 'Is Active', 'Actions'])('renders the %s header', (header) => {
        renderTable({ users: [fakeUserResponse()] });
        expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument();
    });

    it('renders one row per user in desktop table', () => {
        const users = Array.from({ length: 3 }, () => fakeUserResponse());
        const { container } = renderTable({ users });
        const rows = container.querySelectorAll('tbody tr');
        expect(rows).toHaveLength(3);
    });

    it('renders a card for each user for narrow screens', () => {
        renderTable({ users: Array.from({ length: 2 }, () => fakeUserResponse()) });
        expect(within(screen.getByRole('list', { name: 'Users' })).getAllByRole('listitem')).toHaveLength(2);
    });

    it('displays username and email', () => {
        renderTable({ users: [{ ...fakeUserResponse(), username: 'alice', email: 'alice@test.com' }] });
        const aliceTexts = screen.getAllByText('alice');
        expect(aliceTexts.length).toBeGreaterThanOrEqual(1);
        const emailTexts = screen.getAllByText('alice@test.com');
        expect(emailTexts.length).toBeGreaterThanOrEqual(1);
    });

    it('displays role badge', () => {
        renderTable({ users: [{ ...fakeUserResponse(), role: UserRole.ADMIN }] });
        const badges = screen.getAllByText('admin');
        expect(badges.length).toBeGreaterThanOrEqual(1);
    });

    it.each([
        [true, 'Yes'],
        [false, 'No'],
    ] as const)('displays is_active=%s as %s', (isActive, label) => {
        renderTable({ users: [{ ...fakeUserResponse(), is_active: isActive }] });
        const texts = screen.getAllByText(label);
        expect(texts.length).toBeGreaterThanOrEqual(1);
    });

    it.each([
        ['Edit User', 'onEdit'],
        ['Manage Rate Limits', 'onRateLimits'],
        ['Delete User', 'onDelete'],
    ] as const)('calls %s callback when button clicked', async (title, callbackKey) => {
        const mockUser = fakeUserResponse();
        const result = renderTable({ users: [mockUser] });
        const btns = screen.getAllByTitle(title);
        await user.click(btns[0]!);
        expect(result[callbackKey]).toHaveBeenCalledWith(mockUser);
    });

    it('formats created_at timestamp', () => {
        renderTable({ users: [{ ...fakeUserResponse(), created_at: '2024-01-15T10:30:00Z' }] });
        const formatted = screen.getAllByText('formatted:2024-01-15T10:30:00Z');
        expect(formatted.length).toBeGreaterThanOrEqual(1);
    });
});
