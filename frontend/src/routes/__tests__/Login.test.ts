import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { user } from '$test/test-utils';
import { toast } from 'svelte-sonner';
import * as router from '@mateothegreat/svelte5-router';
import * as meta from '$utils/meta';
import Login from '$routes/Login.svelte';

const mocks = vi.hoisted(() => ({
  mockLogin: vi.fn(),
  mockLoadUserSettings: vi.fn(),
  mockGetErrorMessage: vi.fn((err: unknown, fallback?: string) => fallback || String(err)),
  mockAuthStore: {
    login: vi.fn(),
    isAuthenticated: false,
    username: null,
    userRole: null,
    verifyAuth: vi.fn(),
  },
}));

vi.mock('$stores/auth.svelte', () => ({ authStore: mocks.mockAuthStore }));

vi.mock('$lib/user-settings', () => ({
  loadUserSettings: mocks.mockLoadUserSettings,
}));

vi.mock('$lib/api-interceptors', () => ({
  getErrorMessage: mocks.mockGetErrorMessage,
}));

vi.mock('@mateothegreat/svelte5-router', () => ({ route: () => {}, goto: vi.fn() }));

describe('Login', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.mockAuthStore.login = vi.fn().mockResolvedValue(true);
    mocks.mockLoadUserSettings.mockResolvedValue(undefined);
    vi.spyOn(toast, 'success');
    vi.spyOn(toast, 'error');
    vi.spyOn(toast, 'warning');
    vi.spyOn(toast, 'info');
    vi.spyOn(meta, 'updateMetaTags');
  });

  function renderLogin() {
    return render(Login);
  }

  it('renders sign-in form with heading, inputs, button, and register link', async () => {
    await renderLogin();
    expect(screen.getByRole('heading', { name: /sign in to your account/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Username')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /create a new account/i })).toHaveAttribute('href', '/register');
  });

  it('shows auth message from sessionStorage and removes it', async () => {
    sessionStorage.setItem('authMessage', 'Please log in to continue');
    await renderLogin();
    await waitFor(() => {
      expect(toast.info).toHaveBeenCalledWith('Please log in to continue');
    });
    expect(sessionStorage.getItem('authMessage')).toBeNull();
  });

  it('calls authStore.login with exact values, loads settings, shows toast, redirects to /editor', async () => {
    await renderLogin();
    await user.type(screen.getByPlaceholderText('Username'), 'testuser');
    await user.type(screen.getByPlaceholderText('Password'), 'pass1234');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(mocks.mockAuthStore.login).toHaveBeenCalledWith('testuser', 'pass1234');
    });
    expect(mocks.mockLoadUserSettings).toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith('Login successful! Welcome back.');
    expect(router.goto).toHaveBeenCalledWith('/editor');
  });

  it.each([
    ['/settings', '/settings', 'valid relative path'],
    ['/admin/users', '/admin/users', 'valid admin path'],
    ['//evil.com', '/editor', 'protocol-relative URL blocked'],
    ['', '/editor', 'empty string fallback'],
  ])('redirect %s -> navigates to %s (%s)', async (redirectPath, expectedNav) => {
    if (redirectPath) {
      sessionStorage.setItem('redirectAfterLogin', redirectPath);
    }
    await renderLogin();
    await user.type(screen.getByPlaceholderText('Username'), 'u');
    await user.type(screen.getByPlaceholderText('Password'), 'p');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(router.goto).toHaveBeenCalledWith(expectedNav);
    });
    expect(sessionStorage.getItem('redirectAfterLogin')).toBeNull();
  });

  it('shows error message in DOM on login failure (no duplicate toast)', async () => {
    mocks.mockAuthStore.login = vi.fn().mockRejectedValue(new Error('Invalid credentials'));
    mocks.mockGetErrorMessage.mockReturnValue('Login failed. Please check your credentials.');

    await renderLogin();
    await user.type(screen.getByPlaceholderText('Username'), 'bad');
    await user.type(screen.getByPlaceholderText('Password'), 'bad');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText('Login failed. Please check your credentials.')).toBeInTheDocument();
    });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('disables button and shows "Logging in..." during loading', async () => {
    let resolveLogin: (v: boolean) => void;
    mocks.mockAuthStore.login = vi.fn().mockImplementation(
      () => new Promise<boolean>((r) => { resolveLogin = r; })
    );

    await renderLogin();
    await user.type(screen.getByPlaceholderText('Username'), 'u');
    await user.type(screen.getByPlaceholderText('Password'), 'p');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText('Logging in...')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /logging in/i })).toBeDisabled();

    resolveLogin!(true);
    await waitFor(() => {
      expect(screen.queryByText('Logging in...')).not.toBeInTheDocument();
    });
  });

  it('calls updateMetaTags on mount', async () => {
    await renderLogin();
    await waitFor(() => {
      expect(meta.updateMetaTags).toHaveBeenCalledWith('Login', expect.stringContaining('Sign in to Integr8sCode'));
    });
  });
});
