import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

// Mock authStore as a plain object (Svelte 5 runes class pattern)
const mockAuthStore = {
  isAuthenticated: null as boolean | null,
  username: null as string | null,
  userId: null as string | null,
  userRole: null as string | null,
  userEmail: null as string | null,
  csrfToken: null as string | null,
  verifyAuth: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  fetchUserProfile: vi.fn(),
  clearAuth: vi.fn(() => {
    mockAuthStore.isAuthenticated = false;
    mockAuthStore.username = null;
    mockAuthStore.userId = null;
    mockAuthStore.userRole = null;
    mockAuthStore.userEmail = null;
    mockAuthStore.csrfToken = null;
  }),
};

vi.mock('../../stores/auth.svelte', () => ({
  authStore: mockAuthStore,
}));

// Mock clearUserSettings
const mockClearUserSettings = vi.fn();

vi.mock('../../stores/userSettings.svelte', () => ({
  clearUserSettings: () => mockClearUserSettings(),
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

    // Reset authStore mock state
    mockAuthStore.isAuthenticated = null;
    mockAuthStore.username = null;
    mockAuthStore.userId = null;
    mockAuthStore.userRole = null;
    mockAuthStore.userEmail = null;
    mockAuthStore.csrfToken = null;
    mockAuthStore.verifyAuth.mockReset();
    mockAuthStore.login.mockReset();
    mockAuthStore.logout.mockReset();
    mockAuthStore.fetchUserProfile.mockReset();
    mockAuthStore.clearAuth.mockReset().mockImplementation(() => {
      mockAuthStore.isAuthenticated = false;
      mockAuthStore.username = null;
      mockAuthStore.userId = null;
      mockAuthStore.userRole = null;
      mockAuthStore.userEmail = null;
      mockAuthStore.csrfToken = null;
    });

    mockClearUserSettings.mockReset();
    mockLoadUserSettings.mockReset();

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
      mockAuthStore.verifyAuth.mockResolvedValue(false);

      const { AuthInitializer } = await import('$lib/auth-init');
      const result = await AuthInitializer.initialize();

      expect(result).toBe(false);
    });

    it('returns true when no persisted auth but verification succeeds', async () => {
      mockAuthStore.verifyAuth.mockResolvedValue(true);

      const { AuthInitializer } = await import('$lib/auth-init');
      const result = await AuthInitializer.initialize();

      expect(result).toBe(true);
    });

    it('only initializes once', async () => {
      mockAuthStore.verifyAuth.mockResolvedValue(true);

      const { AuthInitializer } = await import('$lib/auth-init');
      await AuthInitializer.initialize();
      await AuthInitializer.initialize();
      await AuthInitializer.initialize();

      expect(mockAuthStore.verifyAuth).toHaveBeenCalledTimes(1);
    });

    it('handles concurrent initialization calls', async () => {
      mockAuthStore.verifyAuth.mockImplementation(() =>
        new Promise(resolve => setTimeout(() => resolve(true), 100))
      );

      const { AuthInitializer } = await import('$lib/auth-init');

      const results = await Promise.all([
        AuthInitializer.initialize(),
        AuthInitializer.initialize(),
        AuthInitializer.initialize(),
      ]);

      expect(results).toEqual([true, true, true]);
      expect(mockAuthStore.verifyAuth).toHaveBeenCalledTimes(1);
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
      mockAuthStore.verifyAuth.mockResolvedValue(true);

      const { AuthInitializer } = await import('$lib/auth-init');
      await AuthInitializer.initialize();

      expect(mockAuthStore.isAuthenticated).toBe(true);
      expect(mockAuthStore.username).toBe('testuser');
      expect(mockAuthStore.userId).toBe('user-123');
      expect(mockAuthStore.userRole).toBe('admin');
      expect(mockAuthStore.userEmail).toBe('test@example.com');
      expect(mockAuthStore.csrfToken).toBe('csrf-token');
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
      mockAuthStore.verifyAuth.mockResolvedValue(false);

      const { AuthInitializer } = await import('$lib/auth-init');
      await AuthInitializer.initialize();

      expect(mockAuthStore.clearAuth).toHaveBeenCalled();
      expect(mockAuthStore.isAuthenticated).toBe(false);
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
      mockAuthStore.verifyAuth.mockRejectedValue(new Error('Network error'));

      const { AuthInitializer } = await import('$lib/auth-init');
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
      mockAuthStore.verifyAuth.mockRejectedValue(new Error('Network error'));

      const { AuthInitializer } = await import('$lib/auth-init');
      const result = await AuthInitializer.initialize();

      expect(result).toBe(false);
      expect(mockAuthStore.isAuthenticated).toBe(false);
    });
  });

  describe('isAuthenticated static method', () => {
    it('returns false before initialization', async () => {
      const { AuthInitializer } = await import('$lib/auth-init');

      expect(AuthInitializer.isAuthenticated()).toBe(false);
    });

    it('returns correct value after initialization', async () => {
      mockAuthStore.verifyAuth.mockResolvedValue(true);
      mockAuthStore.isAuthenticated = true;

      const { AuthInitializer } = await import('$lib/auth-init');
      await AuthInitializer.initialize();

      expect(AuthInitializer.isAuthenticated()).toBe(true);
    });
  });

  describe('waitForInit', () => {
    it('returns immediately if already initialized', async () => {
      mockAuthStore.verifyAuth.mockResolvedValue(true);

      const { AuthInitializer } = await import('$lib/auth-init');
      await AuthInitializer.initialize();

      const result = await AuthInitializer.waitForInit();
      expect(result).toBe(true);
      expect(mockAuthStore.verifyAuth).toHaveBeenCalledTimes(1);
    });

    it('waits for pending initialization', async () => {
      let resolveVerify: (value: boolean) => void;
      mockAuthStore.verifyAuth.mockImplementation(() =>
        new Promise(resolve => { resolveVerify = resolve; })
      );

      const { AuthInitializer } = await import('$lib/auth-init');

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
      mockAuthStore.verifyAuth.mockResolvedValue(true);

      const { AuthInitializer } = await import('$lib/auth-init');

      const result = await AuthInitializer.waitForInit();

      expect(result).toBe(true);
      expect(mockAuthStore.verifyAuth).toHaveBeenCalled();
    });
  });

  describe('exported functions', () => {
    it('initializeAuth calls AuthInitializer.initialize', async () => {
      mockAuthStore.verifyAuth.mockResolvedValue(true);

      const { initializeAuth } = await import('$lib/auth-init');
      const result = await initializeAuth();

      expect(result).toBe(true);
    });

    it('waitForAuth calls AuthInitializer.waitForInit', async () => {
      mockAuthStore.verifyAuth.mockResolvedValue(true);

      const { waitForAuth } = await import('$lib/auth-init');
      const result = await waitForAuth();

      expect(result).toBe(true);
    });

    it('checkAuth calls AuthInitializer.isAuthenticated', async () => {
      mockAuthStore.verifyAuth.mockResolvedValue(true);
      mockAuthStore.isAuthenticated = true;

      const { initializeAuth, checkAuth } = await import('$lib/auth-init');
      await initializeAuth();

      expect(checkAuth()).toBe(true);
    });
  });

  describe('error handling', () => {
    it('handles malformed JSON in sessionStorage', async () => {
      sessionStorageData['authState'] = 'not valid json{';
      mockAuthStore.verifyAuth.mockResolvedValue(false);

      const { AuthInitializer } = await import('$lib/auth-init');
      const result = await AuthInitializer.initialize();

      expect(result).toBe(false);
    });

    it('handles loadUserSettings errors gracefully', async () => {
      mockAuthStore.verifyAuth.mockResolvedValue(true);
      mockLoadUserSettings.mockRejectedValue(new Error('Settings error'));

      const { AuthInitializer } = await import('$lib/auth-init');
      const result = await AuthInitializer.initialize();

      // Should still return true even if settings fail
      expect(result).toBe(true);
    });
  });
});
