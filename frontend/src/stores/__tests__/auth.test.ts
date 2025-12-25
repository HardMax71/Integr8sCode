import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { get } from 'svelte/store';
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
      const { isAuthenticated } = await import('../auth');
      expect(get(isAuthenticated)).toBe(null);
    });

    it('has null username initially', async () => {
      const { username } = await import('../auth');
      expect(get(username)).toBe(null);
    });

    it('has null userRole initially', async () => {
      const { userRole } = await import('../auth');
      expect(get(userRole)).toBe(null);
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

      const { isAuthenticated, username, userRole, csrfToken } = await import('../auth');

      expect(get(isAuthenticated)).toBe(true);
      expect(get(username)).toBe('testuser');
      expect(get(userRole)).toBe('user');
      expect(get(csrfToken)).toBe('test-token');
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

      const { login, isAuthenticated, username, userRole, csrfToken } = await import('../auth');

      const result = await login('testuser', 'password123');

      expect(result).toBe(true);
      expect(get(isAuthenticated)).toBe(true);
      expect(get(username)).toBe('testuser');
      expect(get(userRole)).toBe('user');
      expect(get(csrfToken)).toBe('new-csrf-token');
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

      const { login } = await import('../auth');
      await login('testuser', 'password123');

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

      const { login } = await import('../auth');

      await expect(login('baduser', 'badpass')).rejects.toBeDefined();
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

      const { login } = await import('../auth');
      await login('testuser', 'mypassword');

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

      const { login, logout, isAuthenticated, username } = await import('../auth');

      await login('testuser', 'password');
      expect(get(isAuthenticated)).toBe(true);

      await logout();

      expect(get(isAuthenticated)).toBe(false);
      expect(get(username)).toBe(null);
    });

    it('clears sessionStorage on logout', async () => {
      mockLogoutApi.mockResolvedValue({ data: {}, error: null });

      const { logout } = await import('../auth');
      await logout();

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

      const { login, logout, isAuthenticated } = await import('../auth');

      await login('testuser', 'password');
      await logout();

      expect(get(isAuthenticated)).toBe(false);
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

      const { verifyAuth } = await import('../auth');
      const result = await verifyAuth(true);

      expect(result).toBe(true);
    });

    it('returns false and clears state when verification fails', async () => {
      mockVerifyTokenApi.mockResolvedValue({
        data: { valid: false },
        error: null,
      });

      const { verifyAuth, isAuthenticated } = await import('../auth');
      const result = await verifyAuth(true);

      expect(result).toBe(false);
      expect(get(isAuthenticated)).toBe(false);
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

      const { verifyAuth } = await import('../auth');

      // First call - should hit API
      await verifyAuth(true);
      expect(mockVerifyTokenApi).toHaveBeenCalledTimes(1);

      // Second call without force - should use cache
      await verifyAuth(false);
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

      const { verifyAuth } = await import('../auth');

      await verifyAuth(true);
      await verifyAuth(true);

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

      const { verifyAuth } = await import('../auth');

      const firstResult = await verifyAuth(true);
      expect(firstResult).toBe(true);

      // Second call with network error
      mockVerifyTokenApi.mockRejectedValueOnce(new Error('Network error'));

      const secondResult = await verifyAuth(true);
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

      const { login, userId, userEmail } = await import('../auth');
      await login('testuser', 'password');

      expect(get(userId)).toBe('user-456');
      expect(get(userEmail)).toBe('newemail@example.com');
    });

    it('throws error on failed profile fetch', async () => {
      mockGetProfileApi.mockResolvedValue({
        data: null,
        error: { detail: 'Unauthorized' },
      });

      const { fetchUserProfile } = await import('../auth');

      await expect(fetchUserProfile()).rejects.toBeDefined();
    });
  });
});
