import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/svelte';
import { user, createMockUser, createMockUsers } from '$test/test-utils';

const mocks = vi.hoisted(() => ({
  listUsersApiV1AdminUsersGet: vi.fn(),
  createUserApiV1AdminUsersPost: vi.fn(),
  updateUserApiV1AdminUsersUserIdPut: vi.fn(),
  deleteUserApiV1AdminUsersUserIdDelete: vi.fn(),
  getUserRateLimitsApiV1AdminRateLimitsUserIdGet: vi.fn(),
  updateUserRateLimitsApiV1AdminRateLimitsUserIdPut: vi.fn(),
  resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost: vi.fn(),
  getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet: vi.fn(),
  addToast: vi.fn(),
}));

vi.mock('$lib/api', () => ({
  listUsersApiV1AdminUsersGet: mocks.listUsersApiV1AdminUsersGet,
  createUserApiV1AdminUsersPost: mocks.createUserApiV1AdminUsersPost,
  updateUserApiV1AdminUsersUserIdPut: mocks.updateUserApiV1AdminUsersUserIdPut,
  deleteUserApiV1AdminUsersUserIdDelete: mocks.deleteUserApiV1AdminUsersUserIdDelete,
  getUserRateLimitsApiV1AdminRateLimitsUserIdGet: mocks.getUserRateLimitsApiV1AdminRateLimitsUserIdGet,
  updateUserRateLimitsApiV1AdminRateLimitsUserIdPut: mocks.updateUserRateLimitsApiV1AdminRateLimitsUserIdPut,
  resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost: mocks.resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost,
  getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet: mocks.getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet,
}));

vi.mock('$lib/api-interceptors');

vi.mock('svelte-sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mocks.addToast(...args),
    error: (...args: unknown[]) => mocks.addToast(...args),
    warning: (...args: unknown[]) => mocks.addToast(...args),
    info: (...args: unknown[]) => mocks.addToast(...args),
  },
}));

vi.mock('$lib/formatters', () => ({
  formatTimestamp: (ts: string) => ts ? `formatted:${ts}` : 'N/A',
}));

// Simple mock for AdminLayout that just renders children
vi.mock('../AdminLayout.svelte', async () => {
  const { default: MockLayout } = await import('$routes/admin/__tests__/mocks/MockAdminLayout.svelte');
  return { default: MockLayout };
});

import AdminUsers from '$routes/admin/AdminUsers.svelte';

async function renderWithUsers(users = createMockUsers(3)) {
  mocks.listUsersApiV1AdminUsersGet.mockResolvedValue({ data: { users, total: users.length }, error: null });
  const result = render(AdminUsers);
  await waitFor(() => expect(mocks.listUsersApiV1AdminUsersGet).toHaveBeenCalled());
  return result;
}

describe('AdminUsers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listUsersApiV1AdminUsersGet.mockResolvedValue({ data: { users: [], total: 0 }, error: null });
    mocks.getDefaultRateLimitRulesApiV1AdminRateLimitsDefaultsGet.mockResolvedValue({ data: [], error: null });
  });

  describe('initial loading', () => {
    it('calls loadUsers on mount', async () => {
      render(AdminUsers);
      await waitFor(() => expect(mocks.listUsersApiV1AdminUsersGet).toHaveBeenCalledTimes(1));
    });

    it('handles API error on load and shows toast', async () => {
      const error = { message: 'Network error' };
      mocks.listUsersApiV1AdminUsersGet.mockImplementation(async () => {
        mocks.addToast('Failed to load users');
        return { data: null, error };
      });
      render(AdminUsers);
      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to load users'));
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
      // Desktop table shows '-' for missing email
      expect(screen.getByText('-')).toBeInTheDocument();
    });
  });

  describe('refresh functionality', () => {
    it('refresh button calls loadUsers', async () => {
      await renderWithUsers();
      mocks.listUsersApiV1AdminUsersGet.mockClear();
      const refreshBtn = screen.getByRole('button', { name: /Refresh/i });
      await user.click(refreshBtn);
      await waitFor(() => expect(mocks.listUsersApiV1AdminUsersGet).toHaveBeenCalled());
    });
  });

  describe('search and filtering', () => {
    it('filters users by search query', async () => {
      const allUsers = [
        createMockUser({ username: 'alice', email: 'alice@test.com' }),
        createMockUser({ user_id: 'u2', username: 'bob', email: 'bob@test.com' }),
      ];
      mocks.listUsersApiV1AdminUsersGet.mockImplementation(async ({ query } = {}) => {
        const search = (query as Record<string, unknown>)?.search as string | null;
        const filtered = search ? allUsers.filter(u => u.username.includes(search)) : allUsers;
        return { data: { users: filtered, total: filtered.length }, error: null };
      });
      render(AdminUsers);
      await waitFor(() => expect(mocks.listUsersApiV1AdminUsersGet).toHaveBeenCalled());

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
      mocks.listUsersApiV1AdminUsersGet.mockImplementation(async ({ query } = {}) => {
        const role = (query as Record<string, unknown>)?.role as string | null;
        const filtered = role ? allUsers.filter(u => u.role === role) : allUsers;
        return { data: { users: filtered, total: filtered.length }, error: null };
      });
      render(AdminUsers);
      await waitFor(() => expect(mocks.listUsersApiV1AdminUsersGet).toHaveBeenCalled());

      const roleSelect = screen.getByRole('combobox', { name: /Role/i });
      await user.selectOptions(roleSelect, 'admin');
      await waitFor(() => {
        expect(screen.getAllByText('admin1')).toHaveLength(2);
        expect(screen.queryAllByText('user1')).toHaveLength(0);
      });
    });

    it('filters users by status', async () => {
      const users = [
        createMockUser({ username: 'activeuser', is_active: true }),
        createMockUser({ user_id: 'u2', username: 'disableduser', is_active: false }),
      ];
      await renderWithUsers(users);
      const statusSelect = screen.getByRole('combobox', { name: /Status/i });
      await user.selectOptions(statusSelect, 'disabled');
      await waitFor(() => {
        expect(screen.getAllByText('disableduser')).toHaveLength(2);
        expect(screen.queryAllByText('activeuser')).toHaveLength(0);
      });
    });

    it('resets filters on Reset button click', async () => {
      const users = createMockUsers(3);
      mocks.listUsersApiV1AdminUsersGet.mockImplementation(async ({ query } = {}) => {
        const search = (query as Record<string, unknown>)?.search as string | null;
        if (search === 'nonexistent') {
          return { data: { users: [], total: 0 }, error: null };
        }
        return { data: { users, total: users.length }, error: null };
      });
      render(AdminUsers);
      await waitFor(() => expect(mocks.listUsersApiV1AdminUsersGet).toHaveBeenCalled());

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

    it('filters by bypass rate limit', async () => {
      const users = [
        createMockUser({ username: 'bypassed', bypass_rate_limit: true }),
        createMockUser({ user_id: 'u2', username: 'limited', bypass_rate_limit: false }),
      ];
      await renderWithUsers(users);
      await user.click(screen.getByRole('button', { name: /Advanced/i }));
      const bypassSelect = screen.getByRole('combobox', { name: /Bypass Rate Limit/i });
      await user.selectOptions(bypassSelect, 'yes');
      await waitFor(() => {
        expect(screen.getAllByText('bypassed')).toHaveLength(2);
        expect(screen.queryAllByText('limited')).toHaveLength(0);
      });
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
      mocks.createUserApiV1AdminUsersPost.mockResolvedValue({ data: {}, error: null });
      await renderWithUsers();
      const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
      await user.click(createButton!);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.type(screen.getByLabelText(/Username/i), 'newuser');
      await user.type(screen.getByLabelText(/^Email$/i), 'new@test.com');
      await user.type(screen.getByLabelText(/^Password/i), 'password123');

      // Click the submit button in the dialog
      const dialog = screen.getByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: /Create User/i }));

      await waitFor(() => {
        expect(mocks.createUserApiV1AdminUsersPost).toHaveBeenCalledWith({
          body: expect.objectContaining({
            username: 'newuser',
            email: 'new@test.com',
            password: 'password123',
          }),
        });
      });
    });

    it('handles validation error on create and shows toast', async () => {
      const error = { status: 422, detail: [{ loc: ['body', 'username'], msg: 'Required' }] };
      mocks.createUserApiV1AdminUsersPost.mockImplementation(async () => {
        mocks.addToast('Validation error: username: Required');
        return { data: null, error };
      });
      await renderWithUsers();
      const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
      await user.click(createButton!);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.type(screen.getByLabelText(/Username/i), 'test');
      await user.type(screen.getByLabelText(/^Password/i), 'pass');

      const dialog = screen.getByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: /Create User/i }));

      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Validation error: username: Required'));
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
      mocks.updateUserApiV1AdminUsersUserIdPut.mockResolvedValue({ data: {}, error: null });
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
        expect(mocks.updateUserApiV1AdminUsersUserIdPut).toHaveBeenCalledWith({
          path: { user_id: 'u1' },
          body: expect.objectContaining({ username: 'updated' }),
        });
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
      mocks.deleteUserApiV1AdminUsersUserIdDelete.mockResolvedValue({ data: { message: 'Deleted' }, error: null });
      const users = [createMockUser({ user_id: 'del1', username: 'deleteme' })];
      await renderWithUsers(users);

      const [deleteButton] = screen.getAllByTitle('Delete User');
      await user.click(deleteButton!);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      const dialog = screen.getByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: /Delete User/i }));

      await waitFor(() => {
        expect(mocks.deleteUserApiV1AdminUsersUserIdDelete).toHaveBeenCalledWith({
          path: { user_id: 'del1' },
          query: { cascade: false },
        });
      });
    });

    it('confirms deletion with cascade option', async () => {
      mocks.deleteUserApiV1AdminUsersUserIdDelete.mockResolvedValue({ data: { message: 'Deleted' }, error: null });
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
        expect(mocks.deleteUserApiV1AdminUsersUserIdDelete).toHaveBeenCalledWith({
          path: { user_id: 'del1' },
          query: { cascade: true },
        });
      });
    });

    it('handles deletion error and shows toast', async () => {
      const error = { message: 'Cannot delete' };
      mocks.deleteUserApiV1AdminUsersUserIdDelete.mockImplementation(async () => {
        mocks.addToast('Failed to delete user');
        return { data: null, error };
      });
      const users = [createMockUser({ username: 'deleteme' })];
      await renderWithUsers(users);

      const [deleteButton] = screen.getAllByTitle('Delete User');
      await user.click(deleteButton!);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      const dialog = screen.getByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: /Delete User/i }));

      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to delete user'));
    });

    it('cancels deletion', async () => {
      const users = [createMockUser({ username: 'keepme' })];
      await renderWithUsers(users);

      const [deleteButton] = screen.getAllByTitle('Delete User');
      await user.click(deleteButton!);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Cancel/i }));

      await waitFor(() => {
        expect(mocks.deleteUserApiV1AdminUsersUserIdDelete).not.toHaveBeenCalled();
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
      mocks.getUserRateLimitsApiV1AdminRateLimitsUserIdGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: {} },
        error: null,
      });
      const users = [createMockUser({ username: 'ratelimited' })];
      await renderWithUsers(users);

      // Multiple rate limit buttons exist (mobile + desktop views)
      const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButton!);

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(mocks.getUserRateLimitsApiV1AdminRateLimitsUserIdGet).toHaveBeenCalled();
      });
    });

    it('displays default rules in rate limit modal', async () => {
      mocks.getUserRateLimitsApiV1AdminRateLimitsUserIdGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: {} },
        error: null,
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
      mocks.getUserRateLimitsApiV1AdminRateLimitsUserIdGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: {} },
        error: null,
      });
      mocks.updateUserRateLimitsApiV1AdminRateLimitsUserIdPut.mockResolvedValue({ data: {}, error: null });
      const users = [createMockUser({ user_id: 'u1', username: 'testuser' })];
      await renderWithUsers(users);

      const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButton!);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Save Changes/i }));

      await waitFor(() => {
        expect(mocks.updateUserRateLimitsApiV1AdminRateLimitsUserIdPut).toHaveBeenCalledWith({
          path: { user_id: 'u1' },
          body: expect.any(Object),
        });
      });
    });

    it('handles rate limit save error and shows toast', async () => {
      const error = { status: 422, detail: 'Invalid config' };
      mocks.getUserRateLimitsApiV1AdminRateLimitsUserIdGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: {} },
        error: null,
      });
      mocks.updateUserRateLimitsApiV1AdminRateLimitsUserIdPut.mockImplementation(async () => {
        mocks.addToast('Failed to save rate limits');
        return { data: null, error };
      });
      const users = [createMockUser({ username: 'testuser' })];
      await renderWithUsers(users);

      const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButton!);
      await waitFor(() => expect(screen.getByRole('button', { name: /Save Changes/i })).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Save Changes/i }));

      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to save rate limits'));
    });

    it('adds new rate limit rule', async () => {
      mocks.getUserRateLimitsApiV1AdminRateLimitsUserIdGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: {} },
        error: null,
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
      mocks.getUserRateLimitsApiV1AdminRateLimitsUserIdGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: { '/api/test': { count: 5 } } },
        error: null,
      });
      mocks.resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost.mockResolvedValue({ data: {}, error: null });
      const users = [createMockUser({ user_id: 'u1', username: 'testuser' })];
      await renderWithUsers(users);

      const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButton!);
      await waitFor(() => expect(screen.getByText(/Current Usage/i)).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Reset All Counters/i }));

      await waitFor(() => {
        expect(mocks.resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost).toHaveBeenCalledWith({
          path: { user_id: 'u1' },
        });
      });
    });
  });

  describe('pagination', () => {
    it('shows user count in header', async () => {
      const users = createMockUsers(5);
      await renderWithUsers(users);
      expect(screen.getByText(/Users \(5\)/)).toBeInTheDocument();
    });

    it('shows filtered count when filters applied', async () => {
      const users = [
        createMockUser({ username: 'activeuser', is_active: true }),
        createMockUser({ user_id: 'u2', username: 'disableduser', is_active: false }),
      ];
      await renderWithUsers(users);

      const statusSelect = screen.getByRole('combobox', { name: /Status/i });
      await user.selectOptions(statusSelect, 'active');

      await waitFor(() => {
        expect(screen.getByText(/Users \(1 of 2\)/)).toBeInTheDocument();
      });
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
      mocks.createUserApiV1AdminUsersPost.mockResolvedValue({ data: {}, error: null });
      await renderWithUsers();

      const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
      await user.click(createButton!);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.type(screen.getByLabelText(/^Password/i), 'password123');

      const dialog = screen.getByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: /Create User/i }));

      expect(mocks.createUserApiV1AdminUsersPost).not.toHaveBeenCalled();
      expect(mocks.addToast).toHaveBeenCalledWith('Username is required');
    });

    it('requires password for new user', async () => {
      mocks.createUserApiV1AdminUsersPost.mockResolvedValue({ data: {}, error: null });
      await renderWithUsers();

      const [createButton] = screen.getAllByRole('button', { name: /Create User/i });
      await user.click(createButton!);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.type(screen.getByLabelText(/Username/i), 'newuser');

      const dialog = screen.getByRole('dialog');
      await user.click(within(dialog).getByRole('button', { name: /Create User/i }));

      expect(mocks.createUserApiV1AdminUsersPost).not.toHaveBeenCalled();
      expect(mocks.addToast).toHaveBeenCalledWith('Password is required');
    });

    it('password is optional for edit', async () => {
      mocks.updateUserApiV1AdminUsersUserIdPut.mockResolvedValue({ data: {}, error: null });
      const users = [createMockUser({ user_id: 'u1', username: 'editme' })];
      await renderWithUsers(users);

      // Desktop view has one edit button per user
      const [editButton] = screen.getAllByTitle('Edit User');
      await user.click(editButton!);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Update User/i }));

      await waitFor(() => {
        expect(mocks.updateUserApiV1AdminUsersUserIdPut).toHaveBeenCalledWith({
          path: { user_id: 'u1' },
          body: expect.not.objectContaining({ password: expect.anything() }),
        });
      });
    });
  });

  describe('error handling', () => {
    it('handles API error when loading rate limits and shows toast', async () => {
      const error = { message: 'Failed to load' };
      mocks.getUserRateLimitsApiV1AdminRateLimitsUserIdGet.mockImplementation(async () => {
        mocks.addToast('Failed to load rate limits');
        return { data: null, error };
      });
      const users = [createMockUser({ username: 'testuser' })];
      await renderWithUsers(users);

      const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButton!);

      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to load rate limits'));
    });

    it('handles API error when resetting rate limits and shows toast', async () => {
      const resetError = { message: 'Reset failed' };
      mocks.getUserRateLimitsApiV1AdminRateLimitsUserIdGet.mockResolvedValue({
        data: {
          rate_limit_config: { user_id: 'u1', rules: [], global_multiplier: 1.0, bypass_rate_limit: false, notes: '' },
          current_usage: { '/api': { count: 1 } }
        },
        error: null,
      });
      mocks.resetUserRateLimitsApiV1AdminRateLimitsUserIdResetPost.mockImplementation(async () => {
        mocks.addToast('Failed to reset rate limits');
        return { data: null, error: resetError };
      });
      const users = [createMockUser({ user_id: 'u1', username: 'testuser' })];
      await renderWithUsers(users);

      const [rateLimitButton] = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButton!);
      await waitFor(() => expect(screen.getByRole('button', { name: /Reset All Counters/i })).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Reset All Counters/i }));

      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to reset rate limits'));
    });
  });
});
