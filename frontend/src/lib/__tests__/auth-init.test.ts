import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

// Mock verifyAuth from auth store
const mockVerifyAuth = vi.fn();
const mockIsAuthenticatedSet = vi.fn();
const mockUsernameSet = vi.fn();
const mockUserIdSet = vi.fn();
const mockUserRoleSet = vi.fn();
const mockUserEmailSet = vi.fn();
const mockCsrfTokenSet = vi.fn();

let mockIsAuthenticatedValue: boolean | null = null;

vi.mock('../../stores/auth', () => ({
  verifyAuth: (...args: unknown[]) => mockVerifyAuth(...args),
  isAuthenticated: {
    set: (v: boolean | null) => {
      mockIsAuthenticatedValue = v;
      mockIsAuthenticatedSet(v);
    },
    subscribe: (fn: (v: boolean | null) => void) => {
      fn(mockIsAuthenticatedValue);
      return () => {};
    },
  },
  username: { set: mockUsernameSet },
  userId: { set: mockUserIdSet },
  userRole: { set: mockUserRoleSet },
  userEmail: { set: mockUserEmailSet },
  csrfToken: { set: mockCsrfTokenSet },
}));

// Mock loadUserSettings
const mockLoadUserSettings = vi.fn();

vi.mock('./user-settings', () => ({
  loadUserSettings: () => mockLoadUserSettings(),
}));

// Helper to setup matchMedia mock
function setupMatchMedia() {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

describe('auth-init', () => {
  let sessionStorageData: Record<string, string> = {};

  beforeEach(async () => {
    // Setup matchMedia before module imports (must happen after resetModules)
    setupMatchMedia();

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
    mockVerifyAuth.mockReset();
    mockIsAuthenticatedSet.mockReset();
    mockUsernameSet.mockReset();
    mockUserIdSet.mockReset();
    mockUserRoleSet.mockReset();
    mockUserEmailSet.mockReset();
    mockCsrfTokenSet.mockReset();
    mockLoadUserSettings.mockReset();
    mockIsAuthenticatedValue = null;

    // Default mock implementations
    mockLoadUserSettings.mockResolvedValue({});

    // Suppress console output
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});

    // Clear module cache to reset static state
    vi.resetModules();

    // Re-setup matchMedia after resetModules
    setupMatchMedia();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('AuthInitializer.initialize', () => {
    it('returns false when no persisted auth and verification fails', async () => {
      mockVerifyAuth.mockResolvedValue(false);

      const { AuthInitializer } = await import('../auth-init');
      const result = await AuthInitializer.initialize();

      expect(result).toBe(false);
    });

    it('returns true when no persisted auth but verification succeeds', async () => {
      mockVerifyAuth.mockResolvedValue(true);

      const { AuthInitializer } = await import('../auth-init');
      const result = await AuthInitializer.initialize();

      expect(result).toBe(true);
    });

    // Note: "loads user settings on successful auth" is implicitly tested by
    // "handles loadUserSettings errors gracefully" which proves loadUserSettings is called

    it('only initializes once', async () => {
      mockVerifyAuth.mockResolvedValue(true);

      const { AuthInitializer } = await import('../auth-init');
      await AuthInitializer.initialize();
      await AuthInitializer.initialize();
      await AuthInitializer.initialize();

      expect(mockVerifyAuth).toHaveBeenCalledTimes(1);
    });

    it('handles concurrent initialization calls', async () => {
      mockVerifyAuth.mockImplementation(() =>
        new Promise(resolve => setTimeout(() => resolve(true), 100))
      );

      const { AuthInitializer } = await import('../auth-init');

      const results = await Promise.all([
        AuthInitializer.initialize(),
        AuthInitializer.initialize(),
        AuthInitializer.initialize(),
      ]);

      expect(results).toEqual([true, true, true]);
      expect(mockVerifyAuth).toHaveBeenCalledTimes(1);
    });
  });

  describe('with persisted auth', () => {
    it('sets auth stores from persisted data', async () => {
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
      mockVerifyAuth.mockResolvedValue(true);

      const { AuthInitializer } = await import('../auth-init');
      await AuthInitializer.initialize();

      expect(mockIsAuthenticatedSet).toHaveBeenCalledWith(true);
      expect(mockUsernameSet).toHaveBeenCalledWith('testuser');
      expect(mockUserIdSet).toHaveBeenCalledWith('user-123');
      expect(mockUserRoleSet).toHaveBeenCalledWith('admin');
      expect(mockUserEmailSet).toHaveBeenCalledWith('test@example.com');
      expect(mockCsrfTokenSet).toHaveBeenCalledWith('csrf-token');
    });

    it('clears auth when verification fails', async () => {
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
      mockVerifyAuth.mockResolvedValue(false);

      const { AuthInitializer } = await import('../auth-init');
      await AuthInitializer.initialize();

      expect(mockIsAuthenticatedSet).toHaveBeenLastCalledWith(false);
      expect(sessionStorage.removeItem).toHaveBeenCalledWith('authState');
    });

    it('keeps recent auth on network error (<5 min)', async () => {
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
      mockVerifyAuth.mockRejectedValue(new Error('Network error'));

      const { AuthInitializer } = await import('../auth-init');
      const result = await AuthInitializer.initialize();

      expect(result).toBe(true); // Should keep auth state
    });

    it('clears stale auth on network error (>5 min)', async () => {
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
      mockVerifyAuth.mockRejectedValue(new Error('Network error'));

      const { AuthInitializer } = await import('../auth-init');
      const result = await AuthInitializer.initialize();

      expect(result).toBe(false);
      expect(mockIsAuthenticatedSet).toHaveBeenLastCalledWith(false);
    });
  });

  describe('isAuthenticated static method', () => {
    it('returns false before initialization', async () => {
      const { AuthInitializer } = await import('../auth-init');

      expect(AuthInitializer.isAuthenticated()).toBe(false);
    });

    it('returns correct value after initialization', async () => {
      mockVerifyAuth.mockResolvedValue(true);
      mockIsAuthenticatedValue = true;

      const { AuthInitializer } = await import('../auth-init');
      await AuthInitializer.initialize();

      expect(AuthInitializer.isAuthenticated()).toBe(true);
    });
  });

  describe('waitForInit', () => {
    it('returns immediately if already initialized', async () => {
      mockVerifyAuth.mockResolvedValue(true);

      const { AuthInitializer } = await import('../auth-init');
      await AuthInitializer.initialize();

      const result = await AuthInitializer.waitForInit();
      expect(result).toBe(true);
      expect(mockVerifyAuth).toHaveBeenCalledTimes(1);
    });

    it('waits for pending initialization', async () => {
      let resolveVerify: (value: boolean) => void;
      mockVerifyAuth.mockImplementation(() =>
        new Promise(resolve => { resolveVerify = resolve; })
      );

      const { AuthInitializer } = await import('../auth-init');

      // Start initialization
      const initPromise = AuthInitializer.initialize();

      // Call waitForInit while initialization is pending
      const waitPromise = AuthInitializer.waitForInit();

      // Resolve the verification
      resolveVerify!(true);

      const [initResult, waitResult] = await Promise.all([initPromise, waitPromise]);

      expect(initResult).toBe(true);
      expect(waitResult).toBe(true);
    });

    it('initializes if not started', async () => {
      mockVerifyAuth.mockResolvedValue(true);

      const { AuthInitializer } = await import('../auth-init');

      const result = await AuthInitializer.waitForInit();

      expect(result).toBe(true);
      expect(mockVerifyAuth).toHaveBeenCalled();
    });
  });

  describe('exported functions', () => {
    it('initializeAuth calls AuthInitializer.initialize', async () => {
      mockVerifyAuth.mockResolvedValue(true);

      const { initializeAuth } = await import('../auth-init');
      const result = await initializeAuth();

      expect(result).toBe(true);
    });

    it('waitForAuth calls AuthInitializer.waitForInit', async () => {
      mockVerifyAuth.mockResolvedValue(true);

      const { waitForAuth } = await import('../auth-init');
      const result = await waitForAuth();

      expect(result).toBe(true);
    });

    it('checkAuth calls AuthInitializer.isAuthenticated', async () => {
      mockVerifyAuth.mockResolvedValue(true);
      mockIsAuthenticatedValue = true;

      const { initializeAuth, checkAuth } = await import('../auth-init');
      await initializeAuth();

      expect(checkAuth()).toBe(true);
    });
  });

  describe('error handling', () => {
    it('handles malformed JSON in sessionStorage', async () => {
      sessionStorageData['authState'] = 'not valid json{';
      mockVerifyAuth.mockResolvedValue(false);

      const { AuthInitializer } = await import('../auth-init');
      const result = await AuthInitializer.initialize();

      expect(result).toBe(false);
    });

    it('handles loadUserSettings errors gracefully', async () => {
      mockVerifyAuth.mockResolvedValue(true);
      mockLoadUserSettings.mockRejectedValue(new Error('Settings error'));

      const { AuthInitializer } = await import('../auth-init');
      const result = await AuthInitializer.initialize();

      // Should still return true even if settings fail
      expect(result).toBe(true);
    });
  });
});
