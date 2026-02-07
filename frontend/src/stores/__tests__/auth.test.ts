import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { suppressConsoleError, suppressConsoleWarn } from '../../__tests__/test-utils';

// Mock the API functions
const mockLoginApi = vi.fn();
const mockLogoutApi = vi.fn();
const mockVerifyTokenApi = vi.fn();
const mockGetProfileApi = vi.fn();

vi.mock('../../lib/api', () => ({
  loginApiV1AuthLoginPost: (...args: unknown[]) => mockLoginApi(...args),
  logoutApiV1AuthLogoutPost: (...args: unknown[]) => mockLogoutApi(...args),
  verifyTokenApiV1AuthVerifyTokenGet: (...args: unknown[]) => mockVerifyTokenApi(...args),
  getCurrentUserProfileApiV1AuthMeGet: (...args: unknown[]) => mockGetProfileApi(...args),
}));

describe('auth store', () => {
  let sessionStorageData: Record<string, string> = {};

  beforeEach(async () => {
    // Reset sessionStorage mock
    sessionStorageData = {};
    vi.mocked(sessionStorage.getItem).mockImplementation((key: string) => sessionStorageData[key] ?? null);
    vi.mocked(sessionStorage.setItem).mockImplementation((key: string, value: string) => {
      sessionStorageData[key] = value;
    });
    vi.mocked(sessionStorage.removeItem).mockImplementation((key: string) => {
      delete sessionStorageData[key];
    });

    // Reset all mocks
    mockLoginApi.mockReset();
    mockLogoutApi.mockReset();
    mockVerifyTokenApi.mockReset();
    mockGetProfileApi.mockReset();

    // Clear module cache to reset store state
    vi.resetModules();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('initial state', () => {
    it('has null authentication state initially', async () => {
      const { authStore } = await import('$stores/auth.svelte');
      expect(authStore.isAuthenticated).toBe(null);
    });

    it('has null username initially', async () => {
      const { authStore } = await import('$stores/auth.svelte');
      expect(authStore.username).toBe(null);
    });

    it('has null userRole initially', async () => {
      const { authStore } = await import('$stores/auth.svelte');
      expect(authStore.userRole).toBe(null);
    });

    it('restores auth state from sessionStorage', async () => {
      const authState = {
        isAuthenticated: true,
        username: 'testuser',
        userRole: 'user',
        csrfToken: 'test-token',
        userId: 'user-123',
        userEmail: 'test@example.com',
        timestamp: Date.now(),
      };
      sessionStorageData['authState'] = JSON.stringify(authState);

      const { authStore } = await import('$stores/auth.svelte');

      expect(authStore.isAuthenticated).toBe(true);
      expect(authStore.username).toBe('testuser');
      expect(authStore.userRole).toBe('user');
      expect(authStore.csrfToken).toBe('test-token');
    });
  });

  describe('login', () => {
    it('sets auth state on successful login', async () => {
      mockLoginApi.mockResolvedValue({
        data: {
          username: 'testuser',
          role: 'user',
          csrf_token: 'new-csrf-token',
        },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: { user_id: 'user-123', email: 'test@example.com' },
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');

      const result = await authStore.login('testuser', 'password123');

      expect(result).toBe(true);
      expect(authStore.isAuthenticated).toBe(true);
      expect(authStore.username).toBe('testuser');
      expect(authStore.userRole).toBe('user');
      expect(authStore.csrfToken).toBe('new-csrf-token');
    });

    it('persists auth state to sessionStorage on login', async () => {
      mockLoginApi.mockResolvedValue({
        data: {
          username: 'testuser',
          role: 'user',
          csrf_token: 'csrf-token',
        },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: { user_id: 'user-123', email: 'test@example.com' },
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');
      await authStore.login('testuser', 'password123');

      expect(sessionStorage.setItem).toHaveBeenCalledWith(
        'authState',
        expect.stringContaining('testuser')
      );
    });

    it('throws error on failed login', async () => {
      mockLoginApi.mockResolvedValue({
        data: null,
        error: { detail: 'Invalid credentials' },
      });

      const { authStore } = await import('$stores/auth.svelte');

      await expect(authStore.login('baduser', 'badpass')).rejects.toBeDefined();
    });

    it('calls API with correct parameters', async () => {
      mockLoginApi.mockResolvedValue({
        data: { username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: { user_id: 'user-123', email: 'test@example.com' },
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');
      await authStore.login('testuser', 'mypassword');

      expect(mockLoginApi).toHaveBeenCalledWith({
        body: { username: 'testuser', password: 'mypassword', scope: '' },
      });
    });
  });

  describe('logout', () => {
    it('clears auth state on logout', async () => {
      // Set up authenticated state
      mockLoginApi.mockResolvedValue({
        data: { username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: { user_id: 'user-123', email: 'test@example.com' },
        error: null,
      });
      mockLogoutApi.mockResolvedValue({ data: {}, error: null });

      const { authStore } = await import('$stores/auth.svelte');

      await authStore.login('testuser', 'password');
      expect(authStore.isAuthenticated).toBe(true);

      await authStore.logout();

      expect(authStore.isAuthenticated).toBe(false);
      expect(authStore.username).toBe(null);
    });

    it('clears sessionStorage on logout', async () => {
      mockLogoutApi.mockResolvedValue({ data: {}, error: null });

      const { authStore } = await import('$stores/auth.svelte');
      await authStore.logout();

      expect(sessionStorage.removeItem).toHaveBeenCalledWith('authState');
    });

    it('still clears state even if API call fails', async () => {
      const restoreConsole = suppressConsoleError();

      mockLoginApi.mockResolvedValue({
        data: { username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: { user_id: 'user-123', email: 'test@example.com' },
        error: null,
      });
      mockLogoutApi.mockRejectedValue(new Error('Network error'));

      const { authStore } = await import('$stores/auth.svelte');

      await authStore.login('testuser', 'password');
      await authStore.logout();

      expect(authStore.isAuthenticated).toBe(false);
      restoreConsole();
    });
  });

  describe('verifyAuth', () => {
    it('returns true when verification succeeds', async () => {
      mockVerifyTokenApi.mockResolvedValue({
        data: { valid: true, username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: { user_id: 'user-123', email: 'test@example.com' },
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.verifyAuth(true);

      expect(result).toBe(true);
    });

    it('returns false and clears state when verification fails', async () => {
      mockVerifyTokenApi.mockResolvedValue({
        data: { valid: false },
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.verifyAuth(true);

      expect(result).toBe(false);
      expect(authStore.isAuthenticated).toBe(false);
    });

    it('uses cache when not force refreshing', async () => {
      mockVerifyTokenApi.mockResolvedValue({
        data: { valid: true, username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: { user_id: 'user-123', email: 'test@example.com' },
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');

      // First call - should hit API
      await authStore.verifyAuth(true);
      expect(mockVerifyTokenApi).toHaveBeenCalledTimes(1);

      // Second call without force - should use cache
      await authStore.verifyAuth(false);
      expect(mockVerifyTokenApi).toHaveBeenCalledTimes(1);
    });

    it('bypasses cache when force refreshing', async () => {
      mockVerifyTokenApi.mockResolvedValue({
        data: { valid: true, username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: { user_id: 'user-123', email: 'test@example.com' },
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');

      await authStore.verifyAuth(true);
      await authStore.verifyAuth(true);

      expect(mockVerifyTokenApi).toHaveBeenCalledTimes(2);
    });

    it('returns cached value on network error (offline-first)', async () => {
      const restoreConsole = suppressConsoleWarn();

      // First successful verification
      mockVerifyTokenApi.mockResolvedValueOnce({
        data: { valid: true, username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: { user_id: 'user-123', email: 'test@example.com' },
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');

      const firstResult = await authStore.verifyAuth(true);
      expect(firstResult).toBe(true);

      // Second call with network error
      mockVerifyTokenApi.mockRejectedValueOnce(new Error('Network error'));

      const secondResult = await authStore.verifyAuth(true);
      expect(secondResult).toBe(true); // Should return cached value

      restoreConsole();
    });
  });

  describe('fetchUserProfile', () => {
    it('updates userId and userEmail on success', async () => {
      mockLoginApi.mockResolvedValue({
        data: { username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: { user_id: 'user-456', email: 'newemail@example.com' },
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');
      await authStore.login('testuser', 'password');

      expect(authStore.userId).toBe('user-456');
      expect(authStore.userEmail).toBe('newemail@example.com');
    });

    it('throws error on failed profile fetch', async () => {
      mockGetProfileApi.mockResolvedValue({
        data: null,
        error: { detail: 'Unauthorized' },
      });

      const { authStore } = await import('$stores/auth.svelte');

      await expect(authStore.fetchUserProfile()).rejects.toBeDefined();
    });
  });
});
