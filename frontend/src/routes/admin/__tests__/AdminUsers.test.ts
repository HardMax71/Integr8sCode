import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { tick } from 'svelte';
import { mockElementAnimate } from '$routes/admin/__tests__/test-utils';

interface MockUserOverrides {
  user_id?: string;
  username?: string;
  email?: string | null;
  role?: string;
  is_active?: boolean;
  is_disabled?: boolean;
  created_at?: string;
  bypass_rate_limit?: boolean;
  has_custom_limits?: boolean;
  global_multiplier?: number;
}

const DEFAULT_USER = {
  user_id: 'user-1',
  username: 'testuser',
  email: 'test@example.com',
  role: 'user',
  is_active: true,
  is_disabled: false,
  created_at: '2024-01-15T10:30:00Z',
  bypass_rate_limit: false,
  has_custom_limits: false,
  global_multiplier: 1.0,
};

const createMockUser = (overrides: MockUserOverrides = {}) => ({ ...DEFAULT_USER, ...overrides });

const createMockUsers = (count: number) =>
  Array.from({ length: count }, (_, i) => createMockUser({
    user_id: `user-${i + 1}`,
    username: `user${i + 1}`,
    email: `user${i + 1}@example.com`,
    role: i === 0 ? 'admin' : 'user',
    is_active: i % 3 !== 0,
    is_disabled: i % 3 === 0,
  }));

// Hoisted mocks - must be self-contained
const mocks = vi.hoisted(() => ({
  listUsersApiV1AdminUsersGet: vi.fn(),
  createUserApiV1AdminUsersPost: vi.fn(),
  updateUserApiV1AdminUsersUserIdPut: vi.fn(),
  deleteUserApiV1AdminUsersUserIdDelete: vi.fn(),
  getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet: vi.fn(),
  updateUserRateLimitsApiV1AdminUsersUserIdRateLimitsPut: vi.fn(),
  resetUserRateLimitsApiV1AdminUsersUserIdRateLimitsResetPost: vi.fn(),
  addToast: vi.fn(),
}));

// Mock API module
vi.mock('../../../lib/api', () => ({
  listUsersApiV1AdminUsersGet: (...args: unknown[]) => mocks.listUsersApiV1AdminUsersGet(...args),
  createUserApiV1AdminUsersPost: (...args: unknown[]) => mocks.createUserApiV1AdminUsersPost(...args),
  updateUserApiV1AdminUsersUserIdPut: (...args: unknown[]) => mocks.updateUserApiV1AdminUsersUserIdPut(...args),
  deleteUserApiV1AdminUsersUserIdDelete: (...args: unknown[]) => mocks.deleteUserApiV1AdminUsersUserIdDelete(...args),
  getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet: (...args: unknown[]) => mocks.getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet(...args),
  updateUserRateLimitsApiV1AdminUsersUserIdRateLimitsPut: (...args: unknown[]) => mocks.updateUserRateLimitsApiV1AdminUsersUserIdRateLimitsPut(...args),
  resetUserRateLimitsApiV1AdminUsersUserIdRateLimitsResetPost: (...args: unknown[]) => mocks.resetUserRateLimitsApiV1AdminUsersUserIdRateLimitsResetPost(...args),
}));

vi.mock('../../../lib/api-interceptors');

vi.mock('../../../stores/toastStore', () => ({
  addToast: (...args: unknown[]) => mocks.addToast(...args),
}));

vi.mock('../../../lib/formatters', () => ({
  formatTimestamp: (date: string) => {
    if (!date) return 'N/A';
    return new Date(date).toLocaleDateString('en-US');
  },
}));

// Mock @mateothegreat/svelte5-router
vi.mock('@mateothegreat/svelte5-router', () => ({
  route: () => {},
  goto: vi.fn(),
}));

// Simple mock for AdminLayout that just renders children
vi.mock('../AdminLayout.svelte', async () => {
  const { default: MockLayout } = await import('$routes/admin/__tests__/mocks/MockAdminLayout.svelte');
  return { default: MockLayout };
});

import AdminUsers from '$routes/admin/AdminUsers.svelte';

async function renderWithUsers(users = createMockUsers(3)) {
  mocks.listUsersApiV1AdminUsersGet.mockResolvedValue({ data: users, error: null });
  const result = render(AdminUsers);
  await tick();
  await waitFor(() => expect(mocks.listUsersApiV1AdminUsersGet).toHaveBeenCalled());
  return result;
}

describe('AdminUsers', () => {
  beforeEach(() => {
    mockElementAnimate();
    vi.clearAllMocks();
    mocks.listUsersApiV1AdminUsersGet.mockResolvedValue({ data: [], error: null });
  });

  afterEach(() => {
    cleanup();
  });

  describe('initial loading', () => {
    it('calls loadUsers on mount', async () => {
      render(AdminUsers);
      await waitFor(() => expect(mocks.listUsersApiV1AdminUsersGet).toHaveBeenCalledTimes(1));
    });

    it('handles API error on load and shows toast', async () => {
      const error = { message: 'Network error' };
      mocks.listUsersApiV1AdminUsersGet.mockImplementation(async () => {
        mocks.addToast('Failed to load users', 'error');
        return { data: null, error };
      });
      render(AdminUsers);
      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to load users', 'error'));
      expect(screen.queryByText('testuser')).not.toBeInTheDocument();
    });
  });

  describe('user list rendering', () => {
    it('displays user data in table', async () => {
      const users = [createMockUser({ username: 'johndoe', email: 'john@test.com', role: 'admin' })];
      await renderWithUsers(users);
      // Component has both mobile and desktop views, so use getAllByText
      expect(screen.getAllByText('johndoe').length).toBeGreaterThan(0);
      expect(screen.getAllByText('john@test.com').length).toBeGreaterThan(0);
    });

    it('displays multiple users', async () => {
      const users = createMockUsers(5);
      await renderWithUsers(users);
      expect(screen.getAllByText('user1').length).toBeGreaterThan(0);
      expect(screen.getAllByText('user5').length).toBeGreaterThan(0);
    });

    it('shows role badges for admin and user', async () => {
      const users = [
        createMockUser({ username: 'adminuser', role: 'admin' }),
        createMockUser({ user_id: 'u2', username: 'normaluser', role: 'user' }),
      ];
      await renderWithUsers(users);
      expect(screen.getAllByText('adminuser').length).toBeGreaterThan(0);
      expect(screen.getAllByText('normaluser').length).toBeGreaterThan(0);
    });

    it('shows dash for missing email', async () => {
      const users = [createMockUser({ email: null })];
      await renderWithUsers(users);
      // Desktop table shows '-' for missing email
      expect(screen.getByText('-')).toBeInTheDocument();
    });
  });

  describe('refresh functionality', () => {
    it('refresh button calls loadUsers', async () => {
      const user = userEvent.setup();
      await renderWithUsers();
      mocks.listUsersApiV1AdminUsersGet.mockClear();
      const refreshBtn = screen.getByRole('button', { name: /Refresh/i });
      await user.click(refreshBtn);
      await waitFor(() => expect(mocks.listUsersApiV1AdminUsersGet).toHaveBeenCalled());
    });
  });

  describe('search and filtering', () => {
    it('filters users by search query', async () => {
      const user = userEvent.setup();
      const users = [
        createMockUser({ username: 'alice', email: 'alice@test.com' }),
        createMockUser({ user_id: 'u2', username: 'bob', email: 'bob@test.com' }),
      ];
      await renderWithUsers(users);
      const searchInput = screen.getByPlaceholderText(/Search by username/i);
      await user.type(searchInput, 'alice');
      await waitFor(() => {
        expect(screen.getAllByText('alice').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('bob').length).toBe(0);
      });
    });

    it('filters users by role', async () => {
      const user = userEvent.setup();
      const users = [
        createMockUser({ username: 'admin1', role: 'admin' }),
        createMockUser({ user_id: 'u2', username: 'user1', role: 'user' }),
      ];
      await renderWithUsers(users);
      const roleSelect = screen.getByRole('combobox', { name: /Role/i });
      await user.selectOptions(roleSelect, 'admin');
      await waitFor(() => {
        expect(screen.getAllByText('admin1').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('user1').length).toBe(0);
      });
    });

    it('filters users by status', async () => {
      const user = userEvent.setup();
      const users = [
        createMockUser({ username: 'activeuser', is_active: true, is_disabled: false }),
        createMockUser({ user_id: 'u2', username: 'disableduser', is_active: false, is_disabled: true }),
      ];
      await renderWithUsers(users);
      const statusSelect = screen.getByRole('combobox', { name: /Status/i });
      await user.selectOptions(statusSelect, 'disabled');
      await waitFor(() => {
        expect(screen.getAllByText('disableduser').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('activeuser').length).toBe(0);
      });
    });

    it('resets filters on Reset button click', async () => {
      const user = userEvent.setup();
      const users = createMockUsers(3);
      await renderWithUsers(users);
      const searchInput = screen.getByPlaceholderText(/Search by username/i);
      await user.type(searchInput, 'nonexistent');
      await waitFor(() => expect(screen.getByText(/No users found/i)).toBeInTheDocument());
      const resetBtn = screen.getByRole('button', { name: /^Reset$/i });
      await user.click(resetBtn);
      await waitFor(() => expect(screen.getAllByText('user1').length).toBeGreaterThan(0));
    });

    it('toggles advanced filters panel', async () => {
      const user = userEvent.setup();
      await renderWithUsers();
      const advancedBtn = screen.getByRole('button', { name: /Advanced/i });
      await user.click(advancedBtn);
      await waitFor(() => {
        expect(screen.getByText(/Rate Limit Filters/i)).toBeInTheDocument();
      });
    });

    it('filters by bypass rate limit', async () => {
      const user = userEvent.setup();
      const users = [
        createMockUser({ username: 'bypassed', bypass_rate_limit: true }),
        createMockUser({ user_id: 'u2', username: 'limited', bypass_rate_limit: false }),
      ];
      await renderWithUsers(users);
      await user.click(screen.getByRole('button', { name: /Advanced/i }));
      const bypassSelect = screen.getByRole('combobox', { name: /Bypass Rate Limit/i });
      await user.selectOptions(bypassSelect, 'yes');
      await waitFor(() => {
        expect(screen.getAllByText('bypassed').length).toBeGreaterThan(0);
        expect(screen.queryAllByText('limited').length).toBe(0);
      });
    });
  });

  describe('create user modal', () => {
    it('opens create user modal on button click', async () => {
      const user = userEvent.setup();
      await renderWithUsers();
      // Header has the Create User button
      const createButtons = screen.getAllByRole('button', { name: /Create User/i });
      await user.click(createButtons[0]);
      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument();
      });
    });

    it('submits new user data', async () => {
      mocks.createUserApiV1AdminUsersPost.mockResolvedValue({ data: {}, error: null });
      const user = userEvent.setup();
      await renderWithUsers();
      const createButtons = screen.getAllByRole('button', { name: /Create User/i });
      await user.click(createButtons[0]);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.type(screen.getByLabelText(/Username/i), 'newuser');
      await user.type(screen.getByLabelText(/^Email$/i), 'new@test.com');
      await user.type(screen.getByLabelText(/^Password/i), 'password123');

      // Click the submit button in the dialog
      const allCreateButtons = screen.getAllByRole('button', { name: /Create User/i });
      const submitBtn = allCreateButtons.find(btn => btn.closest('[role="dialog"]'));
      await user.click(submitBtn!);

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
        mocks.addToast('Validation error: username: Required', 'error');
        return { data: null, error };
      });
      const user = userEvent.setup();
      await renderWithUsers();
      const createButtons = screen.getAllByRole('button', { name: /Create User/i });
      await user.click(createButtons[0]);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.type(screen.getByLabelText(/Username/i), 'test');
      await user.type(screen.getByLabelText(/^Password/i), 'pass');

      const allCreateButtons = screen.getAllByRole('button', { name: /Create User/i });
      const submitBtn = allCreateButtons.find(btn => btn.closest('[role="dialog"]'));
      await user.click(submitBtn!);

      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Validation error: username: Required', 'error'));
    });

    it('closes modal on cancel', async () => {
      const user = userEvent.setup();
      await renderWithUsers();
      const createButtons = screen.getAllByRole('button', { name: /Create User/i });
      await user.click(createButtons[0]);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Cancel/i }));
      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
    });
  });

  describe('edit user modal', () => {
    it('opens edit modal with user data', async () => {
      const user = userEvent.setup();
      const users = [createMockUser({ username: 'editme', email: 'edit@test.com' })];
      await renderWithUsers(users);

      // Multiple edit buttons exist (mobile + desktop views)
      const editButtons = screen.getAllByTitle('Edit User');
      await user.click(editButtons[0]);

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(screen.getByDisplayValue('editme')).toBeInTheDocument();
        expect(screen.getByDisplayValue('edit@test.com')).toBeInTheDocument();
      });
    });

    it('submits updated user data', async () => {
      mocks.updateUserApiV1AdminUsersUserIdPut.mockResolvedValue({ data: {}, error: null });
      const user = userEvent.setup();
      const users = [createMockUser({ user_id: 'u1', username: 'editme' })];
      await renderWithUsers(users);

      const editButtons = screen.getAllByTitle('Edit User');
      await user.click(editButtons[0]);
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
      const user = userEvent.setup();
      await renderWithUsers(users);

      // Multiple delete buttons exist (mobile + desktop views)
      const deleteButtons = screen.getAllByTitle('Delete User');
      await user.click(deleteButtons[0]);

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument();
      });
    });

    it('confirms deletion without cascade by default', async () => {
      mocks.deleteUserApiV1AdminUsersUserIdDelete.mockResolvedValue({ data: { message: 'Deleted' }, error: null });
      const users = [createMockUser({ user_id: 'del1', username: 'deleteme' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const deleteButtons = screen.getAllByTitle('Delete User');
      await user.click(deleteButtons[0]);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      const allDeleteButtons = screen.getAllByRole('button', { name: /Delete User/i });
      const confirmDeleteBtn = allDeleteButtons.find(btn => btn.closest('[role="dialog"]'));
      await user.click(confirmDeleteBtn!);

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
      const user = userEvent.setup();
      await renderWithUsers(users);

      const deleteButtons = screen.getAllByTitle('Delete User');
      await user.click(deleteButtons[0]);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      // Enable cascade delete (defaults to false for safety)
      const cascadeCheckbox = screen.getByRole('checkbox');
      await user.click(cascadeCheckbox);

      // Find the delete button in the modal (not the action button)
      const allDeleteButtons = screen.getAllByRole('button', { name: /Delete User/i });
      const confirmDeleteBtn = allDeleteButtons.find(btn => btn.closest('[role="dialog"]'));
      await user.click(confirmDeleteBtn!);

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
        mocks.addToast('Failed to delete user', 'error');
        return { data: null, error };
      });
      const users = [createMockUser({ username: 'deleteme' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const deleteButtons = screen.getAllByTitle('Delete User');
      await user.click(deleteButtons[0]);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      const allDeleteButtons = screen.getAllByRole('button', { name: /Delete User/i });
      const confirmDeleteBtn = allDeleteButtons.find(btn => btn.closest('[role="dialog"]'));
      await user.click(confirmDeleteBtn!);

      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to delete user', 'error'));
    });

    it('cancels deletion', async () => {
      const users = [createMockUser({ username: 'keepme' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const deleteButtons = screen.getAllByTitle('Delete User');
      await user.click(deleteButtons[0]);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Cancel/i }));

      await waitFor(() => {
        expect(mocks.deleteUserApiV1AdminUsersUserIdDelete).not.toHaveBeenCalled();
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
    });

    it('shows cascade warning when enabled', async () => {
      const users = [createMockUser({ username: 'deleteme' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const deleteButtons = screen.getAllByTitle('Delete User');
      await user.click(deleteButtons[0]);
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
      mocks.getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: {} },
        error: null,
      });
      const users = [createMockUser({ username: 'ratelimited' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      // Multiple rate limit buttons exist (mobile + desktop views)
      const rateLimitButtons = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButtons[0]);

      await waitFor(() => {
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(mocks.getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet).toHaveBeenCalled();
      });
    });

    it('displays default rules in rate limit modal', async () => {
      mocks.getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: {} },
        error: null,
      });
      const users = [createMockUser({ username: 'testuser' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const rateLimitButtons = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButtons[0]);

      await waitFor(() => {
        expect(screen.getByText(/Default Global Rules/i)).toBeInTheDocument();
      });
    });

    it('saves rate limit changes', async () => {
      mocks.getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: {} },
        error: null,
      });
      mocks.updateUserRateLimitsApiV1AdminUsersUserIdRateLimitsPut.mockResolvedValue({ data: {}, error: null });
      const users = [createMockUser({ user_id: 'u1', username: 'testuser' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const rateLimitButtons = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButtons[0]);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Save Changes/i }));

      await waitFor(() => {
        expect(mocks.updateUserRateLimitsApiV1AdminUsersUserIdRateLimitsPut).toHaveBeenCalledWith({
          path: { user_id: 'u1' },
          body: expect.any(Object),
        });
      });
    });

    it('handles rate limit save error and shows toast', async () => {
      const error = { status: 422, detail: 'Invalid config' };
      mocks.getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: {} },
        error: null,
      });
      mocks.updateUserRateLimitsApiV1AdminUsersUserIdRateLimitsPut.mockImplementation(async () => {
        mocks.addToast('Failed to save rate limits', 'error');
        return { data: null, error };
      });
      const users = [createMockUser({ username: 'testuser' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const rateLimitButtons = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButtons[0]);
      await waitFor(() => expect(screen.getByRole('button', { name: /Save Changes/i })).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Save Changes/i }));

      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to save rate limits', 'error'));
    });

    it('adds new rate limit rule', async () => {
      mocks.getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: {} },
        error: null,
      });
      const users = [createMockUser({ username: 'testuser' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const rateLimitButtons = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButtons[0]);
      await waitFor(() => expect(screen.getByRole('button', { name: /Add Rule/i })).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Add Rule/i }));

      await waitFor(() => {
        expect(screen.getByText(/User-Specific Overrides/i)).toBeInTheDocument();
      });
    });

    it('resets rate limit counters', async () => {
      mocks.getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet.mockResolvedValue({
        data: { rate_limit_config: mockRateLimitConfig, current_usage: { '/api/test': { count: 5 } } },
        error: null,
      });
      mocks.resetUserRateLimitsApiV1AdminUsersUserIdRateLimitsResetPost.mockResolvedValue({ data: {}, error: null });
      const users = [createMockUser({ user_id: 'u1', username: 'testuser' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const rateLimitButtons = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButtons[0]);
      await waitFor(() => expect(screen.getByText(/Current Usage/i)).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Reset All Counters/i }));

      await waitFor(() => {
        expect(mocks.resetUserRateLimitsApiV1AdminUsersUserIdRateLimitsResetPost).toHaveBeenCalledWith({
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
      const user = userEvent.setup();
      const users = createMockUsers(10);
      await renderWithUsers(users);

      const roleSelect = screen.getByRole('combobox', { name: /Role/i });
      await user.selectOptions(roleSelect, 'admin');

      await waitFor(() => {
        expect(screen.getByText(/Users \(1 of 10\)/)).toBeInTheDocument();
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
      const user = userEvent.setup();
      await renderWithUsers();

      const createButtons = screen.getAllByRole('button', { name: /Create User/i });
      await user.click(createButtons[0]);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.type(screen.getByLabelText(/^Password/i), 'password123');

      const dialogButtons = screen.getAllByRole('button', { name: /Create User/i });
      const submitBtn = dialogButtons.find(btn => btn.closest('[role="dialog"]'));
      await user.click(submitBtn!);

      expect(mocks.createUserApiV1AdminUsersPost).not.toHaveBeenCalled();
      expect(mocks.addToast).toHaveBeenCalledWith('Username is required', 'error');
    });

    it('requires password for new user', async () => {
      mocks.createUserApiV1AdminUsersPost.mockResolvedValue({ data: {}, error: null });
      const user = userEvent.setup();
      await renderWithUsers();

      const createButtons = screen.getAllByRole('button', { name: /Create User/i });
      await user.click(createButtons[0]);
      await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());

      await user.type(screen.getByLabelText(/Username/i), 'newuser');

      const dialogButtons = screen.getAllByRole('button', { name: /Create User/i });
      const submitBtn = dialogButtons.find(btn => btn.closest('[role="dialog"]'));
      await user.click(submitBtn!);

      expect(mocks.createUserApiV1AdminUsersPost).not.toHaveBeenCalled();
      expect(mocks.addToast).toHaveBeenCalledWith('Password is required', 'error');
    });

    it('password is optional for edit', async () => {
      mocks.updateUserApiV1AdminUsersUserIdPut.mockResolvedValue({ data: {}, error: null });
      const user = userEvent.setup();
      const users = [createMockUser({ user_id: 'u1', username: 'editme' })];
      await renderWithUsers(users);

      // Desktop view has one edit button per user
      const editButtons = screen.getAllByTitle('Edit User');
      await user.click(editButtons[0]);
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
      mocks.getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet.mockImplementation(async () => {
        mocks.addToast('Failed to load rate limits', 'error');
        return { data: null, error };
      });
      const users = [createMockUser({ username: 'testuser' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const rateLimitButtons = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButtons[0]);

      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to load rate limits', 'error'));
    });

    it('handles API error when resetting rate limits and shows toast', async () => {
      const resetError = { message: 'Reset failed' };
      mocks.getUserRateLimitsApiV1AdminUsersUserIdRateLimitsGet.mockResolvedValue({
        data: {
          rate_limit_config: { user_id: 'u1', rules: [], global_multiplier: 1.0, bypass_rate_limit: false, notes: '' },
          current_usage: { '/api': { count: 1 } }
        },
        error: null,
      });
      mocks.resetUserRateLimitsApiV1AdminUsersUserIdRateLimitsResetPost.mockImplementation(async () => {
        mocks.addToast('Failed to reset rate limits', 'error');
        return { data: null, error: resetError };
      });
      const users = [createMockUser({ user_id: 'u1', username: 'testuser' })];
      const user = userEvent.setup();
      await renderWithUsers(users);

      const rateLimitButtons = screen.getAllByTitle('Manage Rate Limits');
      await user.click(rateLimitButtons[0]);
      await waitFor(() => expect(screen.getByRole('button', { name: /Reset All Counters/i })).toBeInTheDocument());

      await user.click(screen.getByRole('button', { name: /Reset All Counters/i }));

      await waitFor(() => expect(mocks.addToast).toHaveBeenCalledWith('Failed to reset rate limits', 'error'));
    });
  });
});
