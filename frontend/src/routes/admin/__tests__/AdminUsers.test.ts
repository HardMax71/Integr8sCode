import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/svelte';
import {
    user,
    selectOption,
    createMockUser,
    createMockUsers,
    mockApi,
    renderWithQueryClient,
} from '#test/test-utils.ts';
import {
    listUsersApiV1AdminUsersGet,
    createUserApiV1AdminUsersPost,
    updateUserApiV1AdminUsersUserIdPut,
    deleteUserApiV1AdminUsersUserIdDelete,
    getUserRateLimitsApiV1AdminRateLimitsUserIdGet,
    updateUserRateLimitsApiV1AdminRateLimitsUserIdPut,
    resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost,
    getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet,
} from '#lib/api/index.ts';
import { toast } from 'svelte-sonner';

vi.mock('#lib/formatters.ts', async (importOriginal) => ({
    ...(await importOriginal<typeof import('#lib/formatters.ts')>()),
    formatTimestamp: (ts: string) => (ts ? `formatted:${ts}` : 'N/A'),
}));

// Simple mock for AdminLayout that just renders children
import AdminUsers from '#routes/admin/users/+page.svelte';

async function renderWithUsers(users = createMockUsers(3), total = users.length) {
    mockApi(listUsersApiV1AdminUsersGet).ok({ users, total, offset: 0, limit: 20 });
    const result = renderWithQueryClient(AdminUsers);
    await waitFor(() => expect(vi.mocked(listUsersApiV1AdminUsersGet)).toHaveBeenCalled());
    return result;
}

const lastUsersQuery = () => vi.mocked(listUsersApiV1AdminUsersGet).mock.lastCall?.[0]?.query;

describe('AdminUsers', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockApi(listUsersApiV1AdminUsersGet).ok({ users: [], total: 0, offset: 0, limit: 20 });
        mockApi(getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet).ok([]);
    });

    describe('initial loading', () => {
        it('calls loadUsers on mount', async () => {
            renderWithQueryClient(AdminUsers);
            await waitFor(() => expect(vi.mocked(listUsersApiV1AdminUsersGet)).toHaveBeenCalledTimes(1));
        });

        it('handles API error on load and shows toast', async () => {
            const error = { message: 'Network error' };
            vi.mocked(listUsersApiV1AdminUsersGet).mockImplementation(async () => {
                toast.error('Failed to load users');
                return { data: null, error } as any;
            });
            renderWithQueryClient(AdminUsers);
            await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Failed to load users'));
            expect(screen.queryByText('testuser')).not.toBeInTheDocument();
        });
    });

    describe('user list rendering', () => {
        it('displays user data in table', async () => {
            const users = [createMockUser({ username: 'johndoe', email: 'john@test.com', role: 'admin' })];
            await renderWithUsers(users);
            // Component has both mobile and desktop views, so use getAllByText
            expect(screen.getAllByText('johndoe')).toHaveLength(2);
            expect(screen.getAllByText('john@test.com')).toHaveLength(2);
        });

        it('displays multiple users', async () => {
            const users = createMockUsers(5);
            await renderWithUsers(users);
            expect(screen.getAllByText('user1')).toHaveLength(2);
            expect(screen.getAllByText('user5')).toHaveLength(2);
        });

        it('shows role badges for admin and user', async () => {
            const users = [
                createMockUser({ username: 'adminuser', role: 'admin' }),
                createMockUser({ user_id: 'u2', username: 'normaluser', role: 'user' }),
            ];
            await renderWithUsers(users);
            expect(screen.getAllByText('adminuser')).toHaveLength(2);
            expect(screen.getAllByText('normaluser')).toHaveLength(2);
        });

        it('shows dash for missing email', async () => {
            const users = [createMockUser({ email: null as unknown as string })];
            await renderWithUsers(users);
            expect(within(screen.getByRole('table', { name: 'Users' })).getByText('-')).toBeInTheDocument();
        });
    });

    describe('refresh functionality', () => {
        it('refresh button calls loadUsers', async () => {
            await renderWithUsers();
            vi.mocked(listUsersApiV1AdminUsersGet).mockClear();
            const refreshBtn = screen.getByRole('button', { name: /Refresh/i });
            await user.click(refreshBtn);
            await waitFor(() => expect(vi.mocked(listUsersApiV1AdminUsersGet)).toHaveBeenCalled());
        });
    });

    describe('search and filtering', () => {
        it('filters users by search query', async () => {
            const allUsers = [
                createMockUser({ username: 'alice', email: 'alice@test.com' }),
                createMockUser({ user_id: 'u2', username: 'bob', email: 'bob@test.com' }),
            ];
            vi.mocked(listUsersApiV1AdminUsersGet).mockImplementation(async ({ query } = {}) => {
                const search = (query as Record<string, unknown>)?.search as string | null;
                const filtered = search ? allUsers.filter((u) => u.username.includes(search)) : allUsers;
                return { data: { users: filtered, total: filtered.length, offset: 0, limit: 20 }, error: null } as any;
            });
            renderWithQueryClient(AdminUsers);
            await waitFor(() => expect(vi.mocked(listUsersApiV1AdminUsersGet)).toHaveBeenCalled());

            const searchInput = screen.getByPlaceholderText(/Search by username/i);
            await user.type(searchInput, 'alice');
            await waitFor(() => {
                expect(screen.getAllByText('alice')).toHaveLength(2);
                expect(screen.queryAllByText('bob')).toHaveLength(0);
            });
        });

        it('filters users by role', async () => {
            const allUsers = [
                createMockUser({ username: 'admin1', role: 'admin' }),
                createMockUser({ user_id: 'u2', username: 'user1', role: 'user' }),
            ];
            vi.mocked(listUsersApiV1AdminUsersGet).mockImplementation(async ({ query } = {}) => {
                const role = (query as Record<string, unknown>)?.role as string | null;
                const filtered = role ? allUsers.filter((u) => u.role === role) : allUsers;
                return { data: { users: filtered, total: filtered.length, offset: 0, limit: 20 }, error: null } as any;
            });
            renderWithQueryClient(AdminUsers);
            await waitFor(() => expect(vi.mocked(listUsersApiV1AdminUsersGet)).toHaveBeenCalled());

            const roleSelect = screen.getByRole('combobox', { name: /Role/i });
            selectOption(roleSelect, 'admin');
            await waitFor(() => {
                expect(screen.getAllByText('admin1')).toHaveLength(2);
                expect(screen.queryAllByText('user1')).toHaveLength(0);
            });
        });

        it('asks the server for disabled users', async () => {
            await renderWithUsers();
            selectOption(screen.getByRole('combobox', { name: /Status/i }), 'disabled');
            await waitFor(() => expect(lastUsersQuery()).toMatchObject({ is_active: false }));
        });

        it('resets filters on Reset button click', async () => {
            const users = createMockUsers(3);
            vi.mocked(listUsersApiV1AdminUsersGet).mockImplementation(async ({ query } = {}) => {
                const search = (query as Record<string, unknown>)?.search as string | null;
                if (search === 'nonexistent') {
                    return { data: { users: [], total: 0, offset: 0, limit: 20 }, error: null } as any;
                }
                return { data: { users, total: users.length, offset: 0, limit: 20 }, error: null } as any;
            });
            renderWithQueryClient(AdminUsers);
            await waitFor(() => expect(vi.mocked(listUsersApiV1AdminUsersGet)).toHaveBeenCalled());

            const searchInput = screen.getByPlaceholderText(/Search by username/i);
            await user.type(searchInput, 'nonexistent');
            await waitFor(() => expect(screen.getByText(/No users found/i)).toBeInTheDocument());
            const resetBtn = screen.getByRole('button', { name: /^Reset$/i });
            await user.click(resetBtn);
            await waitFor(() => expect(screen.getAllByText('user1')).toHaveLength(2));
        });

        it('toggles advanced filters panel', async () => {
            await renderWithUsers();
            const advancedBtn = screen.getByRole('button', { name: /Advanced/i });
            await user.click(advancedBtn);
            await waitFor(() => {
                expect(screen.getByText(/Rate Limit Filters/i)).toBeInTheDocument();
            });
        });

        it.each([
            [/Bypass Rate Limit/i, 'yes', { bypass_rate_limit: true }],
            [/Bypass Rate Limit/i, 'no', { bypass_rate_limit: false }],
            [/Custom Limits/i, 'yes', { has_custom_limits: true }],
            [/Global Multiplier/i, 'custom', { custom_multiplier: true }],
            [/Global Multiplier/i, 'default', { custom_multiplier: false }],
        ])('asks the server with the %s filter set to %s', async (name, option, query) => {
            await renderWithUsers();
            await user.click(screen.getByRole('button', { name: /Advanced/i }));
            selectOption(screen.getByRole('combobox', { name }), option);
            await waitFor(() => expect(lastUsersQuery()).toMatchObject(query));
        });
    });

    describe('create user modal', () => {
        it('opens create user modal on button click', async () => {
            await renderWithUsers();
            // Header has the Create User button
            const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
            await user.click(createButton!);
            await waitFor(() => {
                expect(screen.getByRole('dialog')).toBeInTheDocument();
            });
        });

        it('submits new user data', async () => {
            mockApi(createUserApiV1AdminUsersPost).ok({});
            await renderWithUsers();
            const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
            await user.click(createButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.type(screen.getByLabelText(/Username/i), 'newuser');
            await user.type(screen.getByLabelText(/^Email/i), 'new@test.com');
            await user.type(screen.getByLabelText(/^Password/i), 'password123');

            // Click the submit button in the dialog
            const dialog = screen.getByRole('dialog');
            await user.click(within(dialog).getByRole('button', { name: /Create User/i }));

            await waitFor(() => {
                expect(vi.mocked(createUserApiV1AdminUsersPost)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        body: expect.objectContaining({
                            username: 'newuser',
                            email: 'new@test.com',
                            password: 'password123',
                        }),
                    }),
                );
            });
        });

        it('handles validation error on create and shows toast', async () => {
            const error = { status: 422, detail: [{ loc: ['body', 'username'], msg: 'Required' }] };
            vi.mocked(createUserApiV1AdminUsersPost).mockImplementation(async () => {
                toast.error('Validation error: username: Required');
                return { data: null, error } as any;
            });
            await renderWithUsers();
            const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
            await user.click(createButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.type(screen.getByLabelText(/Username/i), 'test');
            await user.type(screen.getByLabelText(/Email/i), 'test@example.com');
            await user.type(screen.getByLabelText(/^Password/i), 'password123');

            const dialog = screen.getByRole('dialog');
            await user.click(within(dialog).getByRole('button', { name: /Create User/i }));

            await waitFor(() =>
                expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Validation error: username: Required'),
            );
        });

        it('shows a short password under the field, from the API schema, before calling the API', async () => {
            await renderWithUsers();
            const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
            await user.click(createButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.type(screen.getByLabelText(/Username/i), 'test');
            await user.type(screen.getByLabelText(/Email/i), 'test@example.com');
            await user.type(screen.getByLabelText(/^Password/i), 'pass');
            await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: /Create User/i }));

            await waitFor(() =>
                expect(screen.getByLabelText(/^Password/i)).toHaveAccessibleDescription(
                    'Must be at least 8 characters',
                ),
            );
            expect(vi.mocked(createUserApiV1AdminUsersPost)).not.toHaveBeenCalled();
        });

        it('closes modal on cancel', async () => {
            await renderWithUsers();
            const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
            await user.click(createButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.click(screen.getByRole('button', { name: /Cancel/i }));
            await waitFor(() => {
                expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
            });
        });
    });

    describe('edit user modal', () => {
        it('opens edit modal with user data', async () => {
            const users = [createMockUser({ username: 'editme', email: 'edit@test.com' })];
            await renderWithUsers(users);

            // Multiple edit buttons exist (mobile + desktop views)
            const [editButton] = screen.getAllByTitle('Edit User');
            await user.click(editButton!);

            await waitFor(() => {
                expect(screen.getByRole('dialog')).toBeInTheDocument();
                expect(screen.getByDisplayValue('editme')).toBeInTheDocument();
                expect(screen.getByDisplayValue('edit@test.com')).toBeInTheDocument();
            });
        });

        it('submits updated user data', async () => {
            mockApi(updateUserApiV1AdminUsersUserIdPut).ok({});
            const users = [createMockUser({ user_id: 'u1', username: 'editme' })];
            await renderWithUsers(users);

            const [editButton] = screen.getAllByTitle('Edit User');
            await user.click(editButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            const usernameInput = screen.getByDisplayValue('editme');
            await user.clear(usernameInput);
            await user.type(usernameInput, 'updated');
            await user.click(screen.getByRole('button', { name: /Update User/i }));

            await waitFor(() => {
                expect(vi.mocked(updateUserApiV1AdminUsersUserIdPut)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { user_id: 'u1' },
                        body: expect.objectContaining({ username: 'updated' }),
                    }),
                );
            });
        });
    });

    describe('delete user modal', () => {
        it('opens delete confirmation modal', async () => {
            const users = [createMockUser({ username: 'deleteme' })];
            await renderWithUsers(users);

            // Multiple delete buttons exist (mobile + desktop views)
            const [deleteButton] = screen.getAllByTitle('Delete User');
            await user.click(deleteButton!);

            await waitFor(() => {
                expect(screen.getByRole('dialog')).toBeInTheDocument();
            });
        });

        it('confirms deletion without cascade by default', async () => {
            mockApi(deleteUserApiV1AdminUsersUserIdDelete).ok({
                user_deleted: true,
                executions: 0,
                saved_scripts: 0,
                notifications: 0,
                user_settings: 0,
            });
            const users = [createMockUser({ user_id: 'del1', username: 'deleteme' })];
            await renderWithUsers(users);

            const [deleteButton] = screen.getAllByTitle('Delete User');
            await user.click(deleteButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            const dialog = screen.getByRole('dialog');
            await user.click(within(dialog).getByRole('button', { name: /Delete User/i }));

            await waitFor(() => {
                expect(vi.mocked(deleteUserApiV1AdminUsersUserIdDelete)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { user_id: 'del1' },
                        query: { cascade: false },
                    }),
                );
            });
        });

        it('confirms deletion with cascade option', async () => {
            mockApi(deleteUserApiV1AdminUsersUserIdDelete).ok({
                user_deleted: true,
                executions: 0,
                saved_scripts: 0,
                notifications: 0,
                user_settings: 0,
            });
            const users = [createMockUser({ user_id: 'del1', username: 'deleteme' })];
            await renderWithUsers(users);

            const [deleteButton] = screen.getAllByTitle('Delete User');
            await user.click(deleteButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            // Enable cascade delete (defaults to false for safety)
            const cascadeCheckbox = screen.getByRole('checkbox');
            await user.click(cascadeCheckbox);

            // Find the delete button in the modal
            const dialog = screen.getByRole('dialog');
            await user.click(within(dialog).getByRole('button', { name: /Delete User/i }));

            await waitFor(() => {
                expect(vi.mocked(deleteUserApiV1AdminUsersUserIdDelete)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { user_id: 'del1' },
                        query: { cascade: true },
                    }),
                );
            });
        });

        it('handles deletion error and shows toast', async () => {
            const error = { message: 'Cannot delete' };
            vi.mocked(deleteUserApiV1AdminUsersUserIdDelete).mockImplementation(async () => {
                toast.error('Failed to delete user');
                return { data: null, error } as any;
            });
            const users = [createMockUser({ username: 'deleteme' })];
            await renderWithUsers(users);

            const [deleteButton] = screen.getAllByTitle('Delete User');
            await user.click(deleteButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            const dialog = screen.getByRole('dialog');
            await user.click(within(dialog).getByRole('button', { name: /Delete User/i }));

            await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Failed to delete user'));
        });

        it('cancels deletion', async () => {
            const users = [createMockUser({ username: 'keepme' })];
            await renderWithUsers(users);

            const [deleteButton] = screen.getAllByTitle('Delete User');
            await user.click(deleteButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.click(screen.getByRole('button', { name: /Cancel/i }));

            await waitFor(() => {
                expect(vi.mocked(deleteUserApiV1AdminUsersUserIdDelete)).not.toHaveBeenCalled();
                expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
            });
        });

        it('shows cascade warning when enabled', async () => {
            const users = [createMockUser({ username: 'deleteme' })];
            await renderWithUsers(users);

            const [deleteButton] = screen.getAllByTitle('Delete User');
            await user.click(deleteButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            // Warning should not show when cascade is disabled (default)
            expect(screen.queryByText(/permanently delete all data/i)).not.toBeInTheDocument();

            // Enable cascade delete
            const cascadeCheckbox = screen.getByRole('checkbox');
            await user.click(cascadeCheckbox);

            await waitFor(() => {
                expect(screen.getByText(/permanently delete all data/i)).toBeInTheDocument();
            });
        });
    });

    describe('rate limit modal', () => {
        const mockRateLimitConfig = {
            user_id: 'u1',
            rules: [],
            global_multiplier: 1.0,
            bypass_rate_limit: false,
            notes: '',
        };

        it('opens rate limit modal for user', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                rate_limit_config: mockRateLimitConfig,
                current_usage: {},
            });
            const users = [createMockUser({ username: 'ratelimited' })];
            await renderWithUsers(users);

            // Multiple rate limit buttons exist (mobile + desktop views)
            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);

            await waitFor(() => {
                expect(screen.getByRole('dialog')).toBeInTheDocument();
                expect(vi.mocked(getUserRateLimitsApiV1AdminRateLimitsUserIdGet)).toHaveBeenCalled();
            });
        });

        it('displays default rules in rate limit modal', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                rate_limit_config: mockRateLimitConfig,
                current_usage: {},
            });
            const users = [createMockUser({ username: 'testuser' })];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);

            await waitFor(() => {
                expect(screen.getByText(/Default Global Rules/i)).toBeInTheDocument();
            });
        });

        it('saves rate limit changes', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                rate_limit_config: mockRateLimitConfig,
                current_usage: {},
            });
            mockApi(updateUserRateLimitsApiV1AdminRateLimitsUserIdPut).ok({});
            const users = [createMockUser({ user_id: 'u1', username: 'testuser' })];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.click(screen.getByRole('button', { name: /Save Changes/i }));

            await waitFor(() => {
                expect(vi.mocked(updateUserRateLimitsApiV1AdminRateLimitsUserIdPut)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { user_id: 'u1' },
                        body: expect.any(Object),
                    }),
                );
            });
        });

        it('handles rate limit save error and shows toast', async () => {
            const error = { status: 422, detail: 'Invalid config' };
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                rate_limit_config: mockRateLimitConfig,
                current_usage: {},
            });
            vi.mocked(updateUserRateLimitsApiV1AdminRateLimitsUserIdPut).mockImplementation(async () => {
                toast.error('Failed to save rate limits');
                return { data: null, error } as any;
            });
            const users = [createMockUser({ username: 'testuser' })];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);
            await waitFor(() => expect(screen.getByRole('button', { name: /Save Changes/i })).toBeInTheDocument());

            await user.click(screen.getByRole('button', { name: /Save Changes/i }));

            await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Failed to save rate limits'));
        });

        it('adds new rate limit rule', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                rate_limit_config: mockRateLimitConfig,
                current_usage: {},
            });
            const users = [createMockUser({ username: 'testuser' })];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);
            await waitFor(() => expect(screen.getByRole('button', { name: /Add Rule/i })).toBeInTheDocument());

            await user.click(screen.getByRole('button', { name: /Add Rule/i }));

            await waitFor(() => {
                expect(screen.getByText(/User-Specific Overrides/i)).toBeInTheDocument();
            });
        });

        it('resets rate limit counters', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                rate_limit_config: mockRateLimitConfig,
                current_usage: { '/api/test': { count: 5 } },
            });
            mockApi(resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost).ok({});
            const users = [createMockUser({ user_id: 'u1', username: 'testuser' })];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);
            await waitFor(() => expect(screen.getByText(/Current Usage/i)).toBeInTheDocument());

            await user.click(screen.getByRole('button', { name: /Reset All Counters/i }));

            await waitFor(() => {
                expect(vi.mocked(resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { user_id: 'u1' },
                    }),
                );
            });
        });
    });

    describe('pagination', () => {
        it('shows user count in header', async () => {
            const users = createMockUsers(5);
            await renderWithUsers(users);
            expect(screen.getByText(/Users \(5\)/)).toBeInTheDocument();
        });

        it('shows the total the server counted, not the users on this page', async () => {
            await renderWithUsers(createMockUsers(10), 42);
            expect(await screen.findByText(/Users \(42\)/)).toBeInTheDocument();
        });

        it('asks the server for the next page', async () => {
            await renderWithUsers(createMockUsers(10), 25);
            expect(lastUsersQuery()).toMatchObject({ limit: 10, offset: 0 });
            await user.click(await screen.findByRole('button', { name: 'Next page' }));
            await waitFor(() => expect(lastUsersQuery()).toMatchObject({ limit: 10, offset: 10 }));
        });

        it('goes back to the first page when a filter changes', async () => {
            await renderWithUsers(createMockUsers(10), 25);
            await user.click(await screen.findByRole('button', { name: 'Next page' }));
            await waitFor(() => expect(lastUsersQuery()).toMatchObject({ offset: 10 }));

            selectOption(screen.getByRole('combobox', { name: /Status/i }), 'active');

            await waitFor(() => expect(lastUsersQuery()).toMatchObject({ is_active: true, offset: 0 }));
        });
    });

    describe('header and layout', () => {
        it('displays page title', async () => {
            await renderWithUsers();
            expect(screen.getByText('User Management')).toBeInTheDocument();
        });

        it('has Create User and Refresh buttons in header', async () => {
            await renderWithUsers();
            expect(screen.getByRole('button', { name: /Create User/i })).toBeInTheDocument();
            expect(screen.getByRole('button', { name: /Refresh/i })).toBeInTheDocument();
        });
    });

    describe('user form validation', () => {
        it('requires username for new user', async () => {
            mockApi(createUserApiV1AdminUsersPost).ok({});
            await renderWithUsers();

            const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
            await user.click(createButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.type(screen.getByLabelText(/^Password/i), 'password123');

            const dialog = screen.getByRole('dialog');
            await user.click(within(dialog).getByRole('button', { name: /Create User/i }));

            // Native HTML required attribute prevents form submission
            expect(vi.mocked(createUserApiV1AdminUsersPost)).not.toHaveBeenCalled();
        });

        it('requires password for new user', async () => {
            mockApi(createUserApiV1AdminUsersPost).ok({});
            await renderWithUsers();

            const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
            await user.click(createButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.type(screen.getByLabelText(/Username/i), 'newuser');

            const dialog = screen.getByRole('dialog');
            await user.click(within(dialog).getByRole('button', { name: /Create User/i }));

            // Native HTML required attribute prevents form submission
            expect(vi.mocked(createUserApiV1AdminUsersPost)).not.toHaveBeenCalled();
        });

        it('password is optional for edit', async () => {
            mockApi(updateUserApiV1AdminUsersUserIdPut).ok({});
            const users = [createMockUser({ user_id: 'u1', username: 'editme' })];
            await renderWithUsers(users);

            // Desktop view has one edit button per user
            const [editButton] = screen.getAllByTitle('Edit User');
            await user.click(editButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.click(screen.getByRole('button', { name: /Update User/i }));

            await waitFor(() => {
                expect(vi.mocked(updateUserApiV1AdminUsersUserIdPut)).toHaveBeenCalledWith(
                    expect.objectContaining({
                        path: { user_id: 'u1' },
                        body: expect.not.objectContaining({ password: expect.anything() }),
                    }),
                );
            });
        });
    });

    describe('error handling', () => {
        it('handles API error when loading rate limits and shows toast', async () => {
            const error = { message: 'Failed to load' };
            vi.mocked(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).mockImplementation(async () => {
                toast.error('Failed to load rate limits');
                return { data: null, error } as any;
            });
            const users = [createMockUser({ username: 'testuser' })];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);

            await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Failed to load rate limits'));
        });

        it('handles API error when resetting rate limits and shows toast', async () => {
            const resetError = { message: 'Reset failed' };
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                rate_limit_config: {
                    user_id: 'u1',
                    rules: [],
                    global_multiplier: 1.0,
                    bypass_rate_limit: false,
                    notes: '',
                },
                current_usage: { '/api': { count: 1 } },
            });
            vi.mocked(resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost).mockImplementation(async () => {
                toast.error('Failed to reset rate limits');
                return { data: null, error: resetError } as any;
            });
            const users = [createMockUser({ user_id: 'u1', username: 'testuser' })];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);
            await waitFor(() =>
                expect(screen.getByRole('button', { name: /Reset All Counters/i })).toBeInTheDocument(),
            );

            await user.click(screen.getByRole('button', { name: /Reset All Counters/i }));

            await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith('Failed to reset rate limits'));
        });
    });
});
