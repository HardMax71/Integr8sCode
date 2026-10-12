import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/svelte';
import { user, selectOption, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import {
    fakeRateLimitUpdateResponse,
    fakeUserRateLimitConfigResponse,
    fakeUserRateLimitsResponse,
    fakeUserResponse,
} from '#lib/api/@faker-js/faker.gen.ts';
import { ApiError } from '#lib/api-error.ts';
import {
    listUsersApiV1AdminUsersGet,
    createUserApiV1AdminUsersPost,
    updateUserApiV1AdminUsersUserIdPut,
    deleteUserApiV1AdminUsersUserIdDelete,
    getUserRateLimitsApiV1AdminRateLimitsUserIdGet,
    updateUserRateLimitsApiV1AdminRateLimitsUserIdPut,
    resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost,
    getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet,
    UserRole,
    zDeleteUserResponse,
    zRateLimitUpdateRequest,
    type HttpValidationError,
    type UserRateLimitConfigResponse,
} from '#lib/api/index.ts';

vi.mock('#lib/formatters.ts', async (importOriginal) => ({
    ...(await importOriginal<typeof import('#lib/formatters.ts')>()),
    formatTimestamp: (ts: string) => (ts ? `formatted:${ts}` : 'N/A'),
}));

// Simple mock for AdminLayout that just renders children
import AdminUsers from '#routes/admin/users/+page.svelte';

async function renderWithUsers(users = Array.from({ length: 3 }, () => fakeUserResponse()), total = users.length) {
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

        it('shows no users when loading fails', async () => {
            mockApi(listUsersApiV1AdminUsersGet).err(new ApiError(500, { detail: 'Server error', type: null }));
            renderWithQueryClient(AdminUsers);
            await waitFor(() => expect(vi.mocked(listUsersApiV1AdminUsersGet)).toHaveBeenCalled());
            expect(screen.queryByText('testuser')).not.toBeInTheDocument();
        });
    });

    describe('user list rendering', () => {
        it('displays user data in table', async () => {
            const users = [
                { ...fakeUserResponse(), username: 'johndoe', email: 'john@test.com', role: UserRole.ADMIN },
            ];
            await renderWithUsers(users);
            // Component has both mobile and desktop views, so use getAllByText
            expect(screen.getAllByText('johndoe')).toHaveLength(2);
            expect(screen.getAllByText('john@test.com')).toHaveLength(2);
        });

        it('displays multiple users', async () => {
            const users = Array.from({ length: 5 }, (_, i) => ({ ...fakeUserResponse(), username: `user${i + 1}` }));
            await renderWithUsers(users);
            expect(screen.getAllByText('user1')).toHaveLength(2);
            expect(screen.getAllByText('user5')).toHaveLength(2);
        });

        it('shows role badges for admin and user', async () => {
            const users = [
                { ...fakeUserResponse(), username: 'adminuser', role: UserRole.ADMIN },
                { ...fakeUserResponse(), user_id: 'u2', username: 'normaluser', role: UserRole.USER },
            ];
            await renderWithUsers(users);
            expect(screen.getAllByText('adminuser')).toHaveLength(2);
            expect(screen.getAllByText('normaluser')).toHaveLength(2);
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
                { ...fakeUserResponse(), username: 'alice', email: 'alice@test.com' },
                { ...fakeUserResponse(), user_id: 'u2', username: 'bob', email: 'bob@test.com' },
            ];
            mockApi(listUsersApiV1AdminUsersGet).respond((options) => {
                const search = options?.query?.search;
                const filtered = search ? allUsers.filter((u) => u.username.includes(search)) : allUsers;
                return { users: filtered, total: filtered.length, offset: 0, limit: 20 };
            });
            renderWithQueryClient(AdminUsers);
            await waitFor(() => expect(vi.mocked(listUsersApiV1AdminUsersGet)).toHaveBeenCalled());

            const searchInput = screen.getByLabelText('Search');
            await user.type(searchInput, 'alice');
            await waitFor(() => {
                expect(screen.getAllByText('alice')).toHaveLength(2);
                expect(screen.queryAllByText('bob')).toHaveLength(0);
            });
        });

        it('filters users by role', async () => {
            const allUsers = [
                { ...fakeUserResponse(), username: 'admin1', role: UserRole.ADMIN },
                { ...fakeUserResponse(), user_id: 'u2', username: 'user1', role: UserRole.USER },
            ];
            mockApi(listUsersApiV1AdminUsersGet).respond((options) => {
                const role = options?.query?.role;
                const filtered = role ? allUsers.filter((u) => u.role === role) : allUsers;
                return { users: filtered, total: filtered.length, offset: 0, limit: 20 };
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
            selectOption(screen.getByRole('combobox', { name: 'Is Active' }), 'false');
            await waitFor(() => expect(lastUsersQuery()).toMatchObject({ is_active: false }));
        });

        it('resets filters on Reset button click', async () => {
            const users = Array.from({ length: 3 }, (_, i) => ({ ...fakeUserResponse(), username: `user${i + 1}` }));
            mockApi(listUsersApiV1AdminUsersGet).respond((options) =>
                options?.query?.search === 'nonexistent'
                    ? { users: [], total: 0, offset: 0, limit: 20 }
                    : { users, total: users.length, offset: 0, limit: 20 },
            );
            renderWithQueryClient(AdminUsers);
            await waitFor(() => expect(vi.mocked(listUsersApiV1AdminUsersGet)).toHaveBeenCalled());

            const searchInput = screen.getByLabelText('Search');
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
            ['Bypass Rate Limit', 'true', { bypass_rate_limit: true }],
            ['Bypass Rate Limit', 'false', { bypass_rate_limit: false }],
            ['Has Custom Limits', 'true', { has_custom_limits: true }],
            ['Custom Multiplier', 'true', { custom_multiplier: true }],
            ['Custom Multiplier', 'false', { custom_multiplier: false }],
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
            mockApi(createUserApiV1AdminUsersPost).ok(fakeUserResponse());
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

        it('keeps the dialog open when the server rejects a new user', async () => {
            const body: HttpValidationError = {
                detail: [{ loc: ['body', 'username'], msg: 'Required', type: 'missing' }],
            };
            mockApi(createUserApiV1AdminUsersPost).err(new ApiError(422, body));
            await renderWithUsers();
            const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
            await user.click(createButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            await user.type(screen.getByLabelText(/Username/i), 'test');
            await user.type(screen.getByLabelText(/Email/i), 'test@example.com');
            await user.type(screen.getByLabelText(/^Password/i), 'password123');

            const dialog = screen.getByRole('dialog');
            await user.click(within(dialog).getByRole('button', { name: /Create User/i }));

            await waitFor(() => expect(vi.mocked(createUserApiV1AdminUsersPost)).toHaveBeenCalled());
            expect(screen.getByRole('dialog')).toBeInTheDocument();
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
            const users = [{ ...fakeUserResponse(), username: 'editme', email: 'edit@test.com' }];
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
            mockApi(updateUserApiV1AdminUsersUserIdPut).ok(fakeUserResponse());
            const users = [{ ...fakeUserResponse(), user_id: 'u1', username: 'editme', email: 'edit@test.com' }];
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
            const users = [{ ...fakeUserResponse(), username: 'deleteme' }];
            await renderWithUsers(users);

            // Multiple delete buttons exist (mobile + desktop views)
            const [deleteButton] = screen.getAllByTitle('Delete User');
            await user.click(deleteButton!);

            await waitFor(() => {
                expect(screen.getByRole('dialog')).toBeInTheDocument();
            });
        });

        it('confirms deletion without cascade by default', async () => {
            mockApi(deleteUserApiV1AdminUsersUserIdDelete).ok(zDeleteUserResponse.parse({ user_deleted: true }));
            const users = [{ ...fakeUserResponse(), user_id: 'del1', username: 'deleteme' }];
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
            mockApi(deleteUserApiV1AdminUsersUserIdDelete).ok(zDeleteUserResponse.parse({ user_deleted: true }));
            const users = [{ ...fakeUserResponse(), user_id: 'del1', username: 'deleteme' }];
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

        it('keeps the dialog open when deletion fails', async () => {
            mockApi(deleteUserApiV1AdminUsersUserIdDelete).err(
                new ApiError(500, { detail: 'Cannot delete', type: null }),
            );
            const users = [{ ...fakeUserResponse(), username: 'deleteme' }];
            await renderWithUsers(users);

            const [deleteButton] = screen.getAllByTitle('Delete User');
            await user.click(deleteButton!);
            await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

            const dialog = screen.getByRole('dialog');
            await user.click(within(dialog).getByRole('button', { name: /Delete User/i }));

            await waitFor(() => expect(vi.mocked(deleteUserApiV1AdminUsersUserIdDelete)).toHaveBeenCalled());
            expect(screen.getByRole('dialog')).toBeInTheDocument();
        });

        it('cancels deletion', async () => {
            const users = [{ ...fakeUserResponse(), username: 'keepme' }];
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
            const users = [{ ...fakeUserResponse(), username: 'deleteme' }];
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
        const mockRateLimitConfig: UserRateLimitConfigResponse = {
            ...fakeUserRateLimitConfigResponse(),
            ...zRateLimitUpdateRequest.parse({}),
            notes: '',
        };

        it('opens rate limit modal for user', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                ...fakeUserRateLimitsResponse(),
                rate_limit_config: mockRateLimitConfig,
                current_usage: {},
            });
            const users = [{ ...fakeUserResponse(), username: 'ratelimited' }];
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
                ...fakeUserRateLimitsResponse(),
                rate_limit_config: mockRateLimitConfig,
                current_usage: {},
            });
            const users = [{ ...fakeUserResponse(), username: 'testuser' }];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);

            await waitFor(() => {
                expect(screen.getByText(/Default Global Rules/i)).toBeInTheDocument();
            });
        });

        it('saves rate limit changes', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                ...fakeUserRateLimitsResponse(),
                rate_limit_config: mockRateLimitConfig,
                current_usage: {},
            });
            mockApi(updateUserRateLimitsApiV1AdminRateLimitsUserIdPut).ok(fakeRateLimitUpdateResponse());
            const users = [{ ...fakeUserResponse(), user_id: 'u1', username: 'testuser' }];
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

        it('keeps the rate limit dialog open when saving fails', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                ...fakeUserRateLimitsResponse(),
                rate_limit_config: mockRateLimitConfig,
                current_usage: {},
            });
            mockApi(updateUserRateLimitsApiV1AdminRateLimitsUserIdPut).err(
                new ApiError(422, { detail: 'Invalid config', type: null }),
            );
            const users = [{ ...fakeUserResponse(), username: 'testuser' }];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);
            await waitFor(() => expect(screen.getByRole('button', { name: /Save Changes/i })).toBeInTheDocument());

            await user.click(screen.getByRole('button', { name: /Save Changes/i }));

            await waitFor(() =>
                expect(vi.mocked(updateUserRateLimitsApiV1AdminRateLimitsUserIdPut)).toHaveBeenCalled(),
            );
            expect(screen.getByRole('dialog')).toBeInTheDocument();
        });

        it('adds new rate limit rule', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                ...fakeUserRateLimitsResponse(),
                rate_limit_config: mockRateLimitConfig,
                current_usage: {},
            });
            const users = [{ ...fakeUserResponse(), username: 'testuser' }];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);
            await waitFor(() => expect(screen.getByRole('button', { name: /Add Rule/i })).toBeInTheDocument());

            await user.click(screen.getByRole('button', { name: /Add Rule/i }));

            await waitFor(() => {
                expect(screen.getByRole('heading', { name: 'Rules' })).toBeInTheDocument();
            });
        });

        it('resets rate limit counters', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                ...fakeUserRateLimitsResponse(),
                rate_limit_config: mockRateLimitConfig,
                current_usage: { '/api/test': { algorithm: 'sliding_window', remaining: 5 } },
            });
            mockApi(resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost).ok({ message: 'Rate limits reset' });
            const users = [{ ...fakeUserResponse(), user_id: 'u1', username: 'testuser' }];
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
            const users = Array.from({ length: 5 }, () => fakeUserResponse());
            await renderWithUsers(users);
            expect(screen.getByText(/Users \(5\)/)).toBeInTheDocument();
        });

        it('shows the total the server counted, not the users on this page', async () => {
            await renderWithUsers(
                Array.from({ length: 10 }, () => fakeUserResponse()),
                42,
            );
            expect(await screen.findByText(/Users \(42\)/)).toBeInTheDocument();
        });

        it('asks the server for the next page', async () => {
            await renderWithUsers(
                Array.from({ length: 10 }, () => fakeUserResponse()),
                25,
            );
            expect(lastUsersQuery()).toMatchObject({ limit: 10, offset: 0 });
            await user.click(await screen.findByRole('button', { name: 'Next page' }));
            await waitFor(() => expect(lastUsersQuery()).toMatchObject({ limit: 10, offset: 10 }));
        });

        it('goes back to the first page when a filter changes', async () => {
            await renderWithUsers(
                Array.from({ length: 10 }, () => fakeUserResponse()),
                25,
            );
            await user.click(await screen.findByRole('button', { name: 'Next page' }));
            await waitFor(() => expect(lastUsersQuery()).toMatchObject({ offset: 10 }));

            selectOption(screen.getByRole('combobox', { name: 'Is Active' }), 'true');

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
            mockApi(createUserApiV1AdminUsersPost).ok(fakeUserResponse());
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
            mockApi(createUserApiV1AdminUsersPost).ok(fakeUserResponse());
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
            mockApi(updateUserApiV1AdminUsersUserIdPut).ok(fakeUserResponse());
            const users = [{ ...fakeUserResponse(), user_id: 'u1', username: 'editme', email: 'edit@test.com' }];
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
        it('shows no rate limit settings when loading them fails', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).err(
                new ApiError(500, { detail: 'Failed to load', type: null }),
            );
            const users = [{ ...fakeUserResponse(), username: 'testuser' }];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);

            await waitFor(() => expect(vi.mocked(getUserRateLimitsApiV1AdminRateLimitsUserIdGet)).toHaveBeenCalled());
            expect(screen.queryByText('Quick Settings')).not.toBeInTheDocument();
        });

        it('keeps the usage when resetting the counters fails', async () => {
            mockApi(getUserRateLimitsApiV1AdminRateLimitsUserIdGet).ok({
                ...fakeUserRateLimitsResponse(),
                rate_limit_config: {
                    ...fakeUserRateLimitConfigResponse(),
                    ...zRateLimitUpdateRequest.parse({}),
                    notes: '',
                },
                current_usage: { '/api': { algorithm: 'sliding_window', remaining: 1 } },
            });
            mockApi(resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost).err(
                new ApiError(500, { detail: 'Reset failed', type: null }),
            );
            const users = [{ ...fakeUserResponse(), user_id: 'u1', username: 'testuser' }];
            await renderWithUsers(users);

            const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
            await user.click(rateLimitButton!);
            await waitFor(() =>
                expect(screen.getByRole('button', { name: /Reset All Counters/i })).toBeInTheDocument(),
            );

            await user.click(screen.getByRole('button', { name: /Reset All Counters/i }));

            await waitFor(() =>
                expect(vi.mocked(resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost)).toHaveBeenCalled(),
            );
            expect(screen.getByText('/api')).toBeInTheDocument();
        });
    });
});
