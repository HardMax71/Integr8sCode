import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';

// vi.hoisted must contain self-contained code - cannot import external modules
const mocks = vi.hoisted(() => {
  // Mock store factory (must be inline - vi.hoisted runs before imports)
  function createMockStore<T>(initial: T) {
    let value = initial;
    const subscribers = new Set<(v: T) => void>();
    return {
      set(v: T) { value = v; subscribers.forEach(fn => fn(v)); },
      subscribe(fn: (v: T) => void) { fn(value); subscribers.add(fn); return () => subscribers.delete(fn); },
      update(fn: (v: T) => T) { this.set(fn(value)); },
    };
  }

  return {
    mockIsAuthenticated: createMockStore<boolean | null>(null),
    mockWaitForInit: (null as unknown) as ReturnType<typeof import('vitest').vi.fn>,
    mockGoto: (null as unknown) as ReturnType<typeof import('vitest').vi.fn>,
  };
});

// Initialize mocks that need vi.fn() outside of hoisted context
mocks.mockWaitForInit = vi.fn().mockResolvedValue(true);
mocks.mockGoto = vi.fn();

// Mock router - use getter to defer access
vi.mock('@mateothegreat/svelte5-router', () => ({
  get goto() { return (...args: unknown[]) => mocks.mockGoto(...args); },
}));

// Mock auth store - use getter to defer access
vi.mock('../../stores/auth', () => ({
  get isAuthenticated() { return mocks.mockIsAuthenticated; },
}));

// Mock auth-init - use getter to defer access
vi.mock('../../lib/auth-init', () => ({
  get AuthInitializer() {
    return {
      waitForInit: () => mocks.mockWaitForInit(),
      initialize: vi.fn(),
      isAuthenticated: vi.fn(),
    };
  },
}));

// Mock Spinner component with Svelte 5 compatible structure
vi.mock('../Spinner.svelte', () => {
  const MockSpinner = function() {
    return { $$: { on_mount: [], on_destroy: [], before_update: [], after_update: [], context: new Map() } };
  };
  MockSpinner.render = () => ({ html: '<div data-testid="spinner" role="status">Loading...</div>', css: { code: '', map: null }, head: '' });
  return { default: MockSpinner };
});

import ProtectedRoute from '$components/ProtectedRoute.svelte';

describe('ProtectedRoute', () => {
  let sessionStorageData: Record<string, string> = {};
  let originalSessionStorage: Storage;

  beforeEach(() => {
    // Reset stores
    mocks.mockIsAuthenticated.set(null);

    // Reset mocks
    mocks.mockGoto.mockReset();
    mocks.mockWaitForInit.mockReset().mockResolvedValue(true);

    // Mock window.location
    Object.defineProperty(window, 'location', {
      value: {
        pathname: '/protected-page',
        search: '?foo=bar',
        hash: '#section',
      },
      writable: true,
      configurable: true,
    });

    // Mock sessionStorage by replacing the entire object
    sessionStorageData = {};
    originalSessionStorage = window.sessionStorage;
    const mockSessionStorage = {
      getItem: vi.fn((key: string) => sessionStorageData[key] ?? null),
      setItem: vi.fn((key: string, value: string) => {
        sessionStorageData[key] = value;
      }),
      removeItem: vi.fn((key: string) => {
        delete sessionStorageData[key];
      }),
      clear: vi.fn(() => {
        sessionStorageData = {};
      }),
      key: vi.fn((index: number) => Object.keys(sessionStorageData)[index] ?? null),
      get length() {
        return Object.keys(sessionStorageData).length;
      },
    };
    Object.defineProperty(window, 'sessionStorage', {
      value: mockSessionStorage,
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    // Restore original sessionStorage
    Object.defineProperty(window, 'sessionStorage', {
      value: originalSessionStorage,
      writable: true,
      configurable: true,
    });
  });

  describe('loading state', () => {
    it('shows spinner while auth is initializing', async () => {
      // Keep waitForInit pending
      let resolveWaitForInit: () => void;
      mocks.mockWaitForInit.mockImplementation(() => new Promise(resolve => {
        resolveWaitForInit = () => resolve(true);
      }));

      const { container } = render(ProtectedRoute);

      // Should show spinner container
      await waitFor(() => {
        expect(container.querySelector('.min-h-screen')).toBeInTheDocument();
      });

      // Cleanup
      resolveWaitForInit!();
    });

    it('waits for AuthInitializer.waitForInit', async () => {
      mocks.mockIsAuthenticated.set(true);

      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockWaitForInit).toHaveBeenCalled();
      });
    });
  });

  describe('authenticated state', () => {
    beforeEach(() => {
      mocks.mockIsAuthenticated.set(true);
      mocks.mockWaitForInit.mockResolvedValue(true);
    });

    it('does not redirect when authenticated', async () => {
      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockWaitForInit).toHaveBeenCalled();
      });

      // Give time for any potential redirect
      await new Promise(resolve => setTimeout(resolve, 50));

      expect(mocks.mockGoto).not.toHaveBeenCalled();
    });

    it('does not save redirect path when authenticated', async () => {
      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockWaitForInit).toHaveBeenCalled();
      });

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(sessionStorageData['redirectAfterLogin']).toBeUndefined();
    });
  });

  describe('unauthenticated state', () => {
    beforeEach(() => {
      mocks.mockIsAuthenticated.set(false);
      mocks.mockWaitForInit.mockResolvedValue(false);
    });

    it('redirects to /login by default', async () => {
      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalledWith('/login');
      });
    });

    it('redirects to custom redirectTo path', async () => {
      render(ProtectedRoute, { props: { redirectTo: '/custom-login' } });

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalledWith('/custom-login');
      });
    });

    it('saves current path for redirect after login', async () => {
      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalled();
      });

      expect(sessionStorageData['redirectAfterLogin']).toBe('/protected-page?foo=bar#section');
    });

    it('does not save login or register paths for redirect', async () => {
      Object.defineProperty(window, 'location', {
        value: {
          pathname: '/login',
          search: '',
          hash: '',
        },
        writable: true,
        configurable: true,
      });

      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalled();
      });

      expect(sessionStorageData['redirectAfterLogin']).toBeUndefined();
    });

    it('saves auth message to sessionStorage', async () => {
      render(ProtectedRoute, { props: { message: 'Custom auth message' } });

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalled();
      });

      expect(sessionStorageData['authMessage']).toBe('Custom auth message');
    });

    it('uses default message if not provided', async () => {
      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalled();
      });

      expect(sessionStorageData['authMessage']).toBe('Please log in to access this page');
    });
  });

  describe('auth state changes', () => {
    it('redirects when auth becomes false after being true', async () => {
      mocks.mockIsAuthenticated.set(true);
      mocks.mockWaitForInit.mockResolvedValue(true);

      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockWaitForInit).toHaveBeenCalled();
      });

      // Initially should not redirect
      expect(mocks.mockGoto).not.toHaveBeenCalled();

      // Simulate logout
      mocks.mockIsAuthenticated.set(false);

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalledWith('/login');
      });
    });
  });

  describe('props handling', () => {
    it('accepts custom redirectTo prop', async () => {
      mocks.mockIsAuthenticated.set(false);

      render(ProtectedRoute, { props: { redirectTo: '/signin' } });

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalledWith('/signin');
      });
    });

    it('accepts custom message prop', async () => {
      mocks.mockIsAuthenticated.set(false);

      render(ProtectedRoute, { props: { message: 'You need to sign in first' } });

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalled();
      });

      expect(sessionStorageData['authMessage']).toBe('You need to sign in first');
    });
  });

  describe('visual states', () => {
    it('shows full-screen centered container while loading', async () => {
      let resolveWaitForInit: () => void;
      mocks.mockWaitForInit.mockImplementation(() => new Promise(resolve => {
        resolveWaitForInit = () => resolve(true);
      }));

      const { container } = render(ProtectedRoute);

      await waitFor(() => {
        const wrapper = container.querySelector('.min-h-screen.flex.items-center.justify-center');
        expect(wrapper).toBeInTheDocument();
      });

      resolveWaitForInit!();
    });

    it('shows spinner during redirect', async () => {
      mocks.mockIsAuthenticated.set(false);

      const { container } = render(ProtectedRoute);

      // While redirecting, should still show spinner
      await waitFor(() => {
        const wrapper = container.querySelector('.min-h-screen');
        expect(wrapper).toBeInTheDocument();
      });
    });
  });

  describe('edge cases', () => {
    it('handles null isAuthenticated during initialization', async () => {
      mocks.mockIsAuthenticated.set(null);
      mocks.mockWaitForInit.mockResolvedValue(false);

      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalledWith('/login');
      });
    });

    it('handles rapid auth state changes', async () => {
      mocks.mockIsAuthenticated.set(true);
      mocks.mockWaitForInit.mockResolvedValue(true);

      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockWaitForInit).toHaveBeenCalled();
      });

      // Rapidly toggle auth
      mocks.mockIsAuthenticated.set(false);
      mocks.mockIsAuthenticated.set(true);
      mocks.mockIsAuthenticated.set(false);

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalled();
      });
    });

    it('handles empty message prop', async () => {
      mocks.mockIsAuthenticated.set(false);

      render(ProtectedRoute, { props: { message: '' } });

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalled();
      });

      // Empty message should not be saved
      expect(sessionStorageData['authMessage']).toBeUndefined();
    });
  });
});
