import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';

// vi.hoisted must contain self-contained code - cannot import external modules
const mocks = vi.hoisted(() => {
  return {
    mockAuthStore: {
      isAuthenticated: null as boolean | null,
      username: null as string | null,
      userId: null as string | null,
      userRole: null as string | null,
      userEmail: null as string | null,
      csrfToken: null as string | null,
      waitForInit: (null as unknown) as ReturnType<typeof import('vitest').vi.fn>,
    },
    mockGoto: (null as unknown) as ReturnType<typeof import('vitest').vi.fn>,
  };
});

// Initialize mocks that need vi.fn() outside of hoisted context
mocks.mockAuthStore.waitForInit = vi.fn().mockResolvedValue(true);
mocks.mockGoto = vi.fn();

// Mock router - use getter to defer access
vi.mock('@mateothegreat/svelte5-router', () => ({
  get goto() { return (...args: unknown[]) => mocks.mockGoto(...args); },
}));

// Mock auth store - direct object, not writable stores
vi.mock('../../stores/auth.svelte', () => ({
  get authStore() { return mocks.mockAuthStore; },
}));

vi.mock('../Spinner.svelte', async () =>
  (await import('$lib/../__tests__/test-utils')).createMockSvelteComponent(
    '<div role="status">Loading...</div>', 'spinner'));

import ProtectedRoute from '$components/ProtectedRoute.svelte';

describe('ProtectedRoute', () => {
  let sessionStorageData: Record<string, string> = {};
  let originalSessionStorage: Storage;

  beforeEach(() => {
    // Reset stores
    mocks.mockAuthStore.isAuthenticated = null;
    mocks.mockAuthStore.username = null;
    mocks.mockAuthStore.userId = null;
    mocks.mockAuthStore.userRole = null;
    mocks.mockAuthStore.userEmail = null;
    mocks.mockAuthStore.csrfToken = null;

    // Reset mocks
    mocks.mockGoto.mockReset();
    mocks.mockAuthStore.waitForInit.mockReset().mockResolvedValue(true);

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
      mocks.mockAuthStore.waitForInit.mockImplementation(() => new Promise(resolve => {
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

    it('waits for authStore.waitForInit', async () => {
      mocks.mockAuthStore.isAuthenticated = true;

      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockAuthStore.waitForInit).toHaveBeenCalled();
      });
    });
  });

  describe('authenticated state', () => {
    beforeEach(() => {
      mocks.mockAuthStore.isAuthenticated = true;
      mocks.mockAuthStore.waitForInit.mockResolvedValue(true);
    });

    it('does not redirect when authenticated', async () => {
      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockAuthStore.waitForInit).toHaveBeenCalled();
      });

      // Give time for any potential redirect
      await new Promise(resolve => setTimeout(resolve, 50));

      expect(mocks.mockGoto).not.toHaveBeenCalled();
    });

    it('does not save redirect path when authenticated', async () => {
      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockAuthStore.waitForInit).toHaveBeenCalled();
      });

      await new Promise(resolve => setTimeout(resolve, 50));

      expect(sessionStorageData['redirectAfterLogin']).toBeUndefined();
    });
  });

  describe('unauthenticated state', () => {
    beforeEach(() => {
      mocks.mockAuthStore.isAuthenticated = false;
      mocks.mockAuthStore.waitForInit.mockResolvedValue(false);
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

  describe('props handling', () => {
    it('accepts custom redirectTo prop', async () => {
      mocks.mockAuthStore.isAuthenticated = false;

      render(ProtectedRoute, { props: { redirectTo: '/signin' } });

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalledWith('/signin');
      });
    });

    it('accepts custom message prop', async () => {
      mocks.mockAuthStore.isAuthenticated = false;

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
      mocks.mockAuthStore.waitForInit.mockImplementation(() => new Promise(resolve => {
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
      mocks.mockAuthStore.isAuthenticated = false;

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
      mocks.mockAuthStore.isAuthenticated = null;
      mocks.mockAuthStore.waitForInit.mockResolvedValue(false);

      render(ProtectedRoute);

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalledWith('/login');
      });
    });

    it('handles empty message prop', async () => {
      mocks.mockAuthStore.isAuthenticated = false;

      render(ProtectedRoute, { props: { message: '' } });

      await waitFor(() => {
        expect(mocks.mockGoto).toHaveBeenCalled();
      });

      // Empty message should not be saved
      expect(sessionStorageData['authMessage']).toBeUndefined();
    });
  });
});
