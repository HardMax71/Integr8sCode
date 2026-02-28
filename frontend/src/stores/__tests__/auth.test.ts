import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { suppressConsoleError, suppressConsoleWarn } from '$test/test-utils';

const mockLoginApi = vi.fn();
const mockLogoutApi = vi.fn();
const mockGetProfileApi = vi.fn();

vi.mock('../../lib/api', () => ({
  loginApiV1AuthLoginPost: (...args: unknown[]) => mockLoginApi(...args),
  logoutApiV1AuthLogoutPost: (...args: unknown[]) => mockLogoutApi(...args),
  getCurrentUserProfileApiV1AuthMeGet: (...args: unknown[]) => mockGetProfileApi(...args),
}));

// Mock clearUserSettings (static import in auth.svelte.ts)
const mockClearUserSettings = vi.fn();
vi.mock('../userSettings.svelte', () => ({
  clearUserSettings: () => mockClearUserSettings(),
  setUserSettings: vi.fn(),
  userSettingsStore: { settings: null, editorSettings: {} },
}));

// Mock loadUserSettings (dynamic import in auth.svelte.ts)
const mockLoadUserSettings = vi.fn();
vi.mock('../../lib/user-settings', () => ({
  loadUserSettings: () => mockLoadUserSettings(),
}));

const PROFILE_RESPONSE = {
  user_id: 'user-123',
  username: 'testuser',
  email: 'test@example.com',
  role: 'user',
  is_active: true,
  is_superuser: false,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

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
    mockGetProfileApi.mockReset();
    mockClearUserSettings.mockReset();
    mockLoadUserSettings.mockReset().mockResolvedValue({});

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
        data: PROFILE_RESPONSE,
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');

      const result = await authStore.login('testuser', 'password123');

      expect(result).toBe(true);
      expect(authStore.isAuthenticated).toBe(true);
      expect(authStore.username).toBe('testuser');
      expect(authStore.userRole).toBe('user');
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
        data: PROFILE_RESPONSE,
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

    it('returns false when post-login verification fails', async () => {
      mockLoginApi.mockResolvedValue({
        data: { username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({ data: null, error: { detail: 'Unauthorized' } });

      const restoreConsole = suppressConsoleWarn();
      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.login('testuser', 'password123');

      expect(result).toBe(false);
      expect(authStore.isAuthenticated).toBe(false);
      restoreConsole();
    });

    it('returns true when post-login verification throws (network error)', async () => {
      mockLoginApi.mockResolvedValue({
        data: { username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockRejectedValue(new Error('Network error'));

      const restoreConsole = suppressConsoleWarn();
      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.login('testuser', 'password123');

      expect(result).toBe(true);
      expect(authStore.isAuthenticated).toBe(true);
      restoreConsole();
    });

    it('calls API with correct parameters', async () => {
      mockLoginApi.mockResolvedValue({
        data: { username: 'testuser', role: 'user', csrf_token: 'token' },
        error: null,
      });
      mockGetProfileApi.mockResolvedValue({
        data: PROFILE_RESPONSE,
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
        data: PROFILE_RESPONSE,
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
        data: PROFILE_RESPONSE,
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
      mockGetProfileApi.mockResolvedValue({ data: PROFILE_RESPONSE, error: null });

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.verifyAuth(true);

      expect(result).toBe(true);
    });

    it('returns false and clears state when verification fails', async () => {
      mockGetProfileApi.mockResolvedValue({ data: null, error: { detail: 'Unauthorized' } });

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.verifyAuth(true);

      expect(result).toBe(false);
      expect(authStore.isAuthenticated).toBe(false);
    });

    it('uses cache when not force refreshing', async () => {
      mockGetProfileApi.mockResolvedValue({ data: PROFILE_RESPONSE, error: null });

      const { authStore } = await import('$stores/auth.svelte');

      // First call - should hit API
      await authStore.verifyAuth(true);
      expect(mockGetProfileApi).toHaveBeenCalledTimes(1);

      // Second call without force - should use cache
      await authStore.verifyAuth(false);
      expect(mockGetProfileApi).toHaveBeenCalledTimes(1);
    });

    it('bypasses cache when force refreshing', async () => {
      mockGetProfileApi.mockResolvedValue({ data: PROFILE_RESPONSE, error: null });

      const { authStore } = await import('$stores/auth.svelte');

      await authStore.verifyAuth(true);
      await authStore.verifyAuth(true);

      expect(mockGetProfileApi).toHaveBeenCalledTimes(2);
    });

    it('returns cached value on network error (offline-first)', async () => {
      const restoreConsole = suppressConsoleWarn();

      // First successful verification
      mockGetProfileApi.mockResolvedValueOnce({ data: PROFILE_RESPONSE, error: null });

      const { authStore } = await import('$stores/auth.svelte');

      const firstResult = await authStore.verifyAuth(true);
      expect(firstResult).toBe(true);

      // Second call with network error
      mockGetProfileApi.mockRejectedValueOnce(new Error('Network error'));

      const secondResult = await authStore.verifyAuth(true);
      expect(secondResult).toBe(true); // Should return cached value

      restoreConsole();
    });
  });

  describe('initialize', () => {
    it('returns false when no persisted auth and verification fails', async () => {
      mockGetProfileApi.mockResolvedValue({ data: null, error: { detail: 'Unauthorized' } });

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.initialize();

      expect(result).toBe(false);
    });

    it('returns true when no persisted auth but verification succeeds', async () => {
      mockGetProfileApi.mockResolvedValue({ data: PROFILE_RESPONSE, error: null });

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.initialize();

      expect(result).toBe(true);
      expect(mockLoadUserSettings).toHaveBeenCalled();
    });

    it('only initializes once', async () => {
      mockGetProfileApi.mockResolvedValue({ data: PROFILE_RESPONSE, error: null });

      const { authStore } = await import('$stores/auth.svelte');
      await authStore.initialize();
      await authStore.initialize();
      await authStore.initialize();

      expect(mockGetProfileApi).toHaveBeenCalledTimes(1);
    });

    it('handles concurrent initialization calls', async () => {
      mockGetProfileApi.mockImplementation(() =>
        new Promise(resolve => setTimeout(() => resolve({
          data: PROFILE_RESPONSE,
          error: null,
        }), 50))
      );

      const { authStore } = await import('$stores/auth.svelte');
      const results = await Promise.all([
        authStore.initialize(),
        authStore.initialize(),
        authStore.initialize(),
      ]);

      expect(results).toEqual([true, true, true]);
      expect(mockGetProfileApi).toHaveBeenCalledTimes(1);
    });

    it('restores from persisted auth and verifies', async () => {
      const authState = {
        isAuthenticated: true,
        username: 'testuser',
        userId: 'user-123',
        userRole: 'admin',
        userEmail: 'test@example.com',
        csrfToken: 'csrf-token',
        timestamp: Date.now(),
      };
      sessionStorageData['authState'] = JSON.stringify(authState);

      mockGetProfileApi.mockResolvedValue({
        data: { ...PROFILE_RESPONSE, role: 'admin' },
        error: null,
      });

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.initialize();

      expect(result).toBe(true);
      expect(authStore.isAuthenticated).toBe(true);
      expect(authStore.username).toBe('testuser');
    });

    it('clears auth when persisted auth verification fails', async () => {
      const authState = {
        isAuthenticated: true,
        username: 'testuser',
        userId: 'user-123',
        userRole: 'user',
        userEmail: 'test@example.com',
        csrfToken: 'token',
        timestamp: Date.now(),
      };
      sessionStorageData['authState'] = JSON.stringify(authState);

      mockGetProfileApi.mockResolvedValue({ data: null, error: { detail: 'Unauthorized' } });

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.initialize();

      expect(result).toBe(false);
      expect(authStore.isAuthenticated).toBe(false);
      expect(mockClearUserSettings).toHaveBeenCalled();
    });

    it('keeps recent auth on network error (<5 min)', async () => {
      const restoreConsole = suppressConsoleWarn();

      const authState = {
        isAuthenticated: true,
        username: 'testuser',
        userId: 'user-123',
        userRole: 'user',
        userEmail: 'test@example.com',
        csrfToken: 'token',
        timestamp: Date.now() - 2 * 60 * 1000, // 2 minutes ago
      };
      sessionStorageData['authState'] = JSON.stringify(authState);

      mockGetProfileApi.mockRejectedValue(new Error('Network error'));

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.initialize();

      expect(result).toBe(true);
      restoreConsole();
    });

    it('clears stale auth on network error (>5 min)', async () => {
      const restoreConsole = suppressConsoleWarn();

      const authState = {
        isAuthenticated: true,
        username: 'testuser',
        userId: 'user-123',
        userRole: 'user',
        userEmail: 'test@example.com',
        csrfToken: 'token',
        timestamp: Date.now() - 10 * 60 * 1000, // 10 minutes ago
      };
      sessionStorageData['authState'] = JSON.stringify(authState);

      mockGetProfileApi.mockRejectedValue(new Error('Network error'));

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.initialize();

      expect(result).toBe(false);
      expect(authStore.isAuthenticated).toBe(false);
      expect(mockClearUserSettings).toHaveBeenCalled();
      restoreConsole();
    });
  });

  describe('waitForInit', () => {
    it('returns immediately if already initialized', async () => {
      mockGetProfileApi.mockResolvedValue({ data: PROFILE_RESPONSE, error: null });

      const { authStore } = await import('$stores/auth.svelte');
      await authStore.initialize();

      const result = await authStore.waitForInit();
      expect(result).toBe(true);
      expect(mockGetProfileApi).toHaveBeenCalledTimes(1);
    });

    it('initializes if not started', async () => {
      mockGetProfileApi.mockResolvedValue({ data: PROFILE_RESPONSE, error: null });

      const { authStore } = await import('$stores/auth.svelte');
      const result = await authStore.waitForInit();

      expect(result).toBe(true);
      expect(mockGetProfileApi).toHaveBeenCalled();
    });
  });

  describe('logout clears user settings', () => {
    it('calls clearUserSettings on logout', async () => {
      mockLogoutApi.mockResolvedValue({ data: {}, error: null });

      const { authStore } = await import('$stores/auth.svelte');
      await authStore.logout();

      expect(mockClearUserSettings).toHaveBeenCalled();
    });
  });
});
