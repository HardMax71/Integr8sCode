import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { user } from '$test/test-utils';
import { toast } from 'svelte-sonner';
import * as router from '@mateothegreat/svelte5-router';
import * as meta from '$utils/meta';
import Register from '$routes/Register.svelte';

const mocks = vi.hoisted(() => ({
  registerApiV1AuthRegisterPost: vi.fn(),
  mockGetErrorMessage: vi.fn((_err: unknown, fallback?: string) => fallback || 'Unknown error'),
}));

vi.mock('$lib/api', () => ({
  registerApiV1AuthRegisterPost: mocks.registerApiV1AuthRegisterPost,
}));

vi.mock('$lib/api-interceptors', () => ({
  getErrorMessage: mocks.mockGetErrorMessage,
}));

vi.mock('@mateothegreat/svelte5-router', () => ({ route: () => {}, goto: vi.fn() }));

describe('Register', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.registerApiV1AuthRegisterPost.mockResolvedValue({ data: {}, error: undefined });
    vi.spyOn(toast, 'success');
    vi.spyOn(toast, 'error');
    vi.spyOn(toast, 'warning');
    vi.spyOn(toast, 'info');
    vi.spyOn(meta, 'updateMetaTags');
  });

  function renderRegister() {
    return render(Register);
  }

  it('renders form with 4 inputs, submit button, and login link', async () => {
    await renderRegister();
    expect(screen.getByRole('heading', { name: /create a new account/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Username')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Email address')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Password (min. 8 characters)')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Confirm Password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /sign in to your existing account/i })).toHaveAttribute('href', '/login');
  });

  it.each([
    {
      name: 'mismatched passwords',
      password: 'password1',
      confirmPassword: 'password2',
      expectedError: 'Passwords do not match.',
      toastType: 'error',
    },
    {
      name: 'short password',
      password: 'short',
      confirmPassword: 'short',
      expectedError: 'Password must be at least 8 characters long.',
      toastType: 'warning',
    },
  ])('client-side validation: $name', async ({ password, confirmPassword, expectedError, toastType }) => {
    await renderRegister();
    await user.type(screen.getByPlaceholderText('Username'), 'testuser');
    await user.type(screen.getByPlaceholderText('Email address'), 'test@email.com');
    await user.type(screen.getByPlaceholderText('Password (min. 8 characters)'), password);
    await user.type(screen.getByPlaceholderText('Confirm Password'), confirmPassword);
    await user.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText(expectedError)).toBeInTheDocument();
    });
    expect(toast[toastType as keyof typeof toast]).toHaveBeenCalledWith(expectedError);
    expect(mocks.registerApiV1AuthRegisterPost).not.toHaveBeenCalled();
  });

  it('calls API with correct payload, shows toast, and redirects on success', async () => {
    await renderRegister();
    await user.type(screen.getByPlaceholderText('Username'), 'newuser');
    await user.type(screen.getByPlaceholderText('Email address'), 'new@email.com');
    await user.type(screen.getByPlaceholderText('Password (min. 8 characters)'), 'securepass');
    await user.type(screen.getByPlaceholderText('Confirm Password'), 'securepass');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => {
      expect(mocks.registerApiV1AuthRegisterPost).toHaveBeenCalledWith({
        body: { username: 'newuser', email: 'new@email.com', password: 'securepass' },
      });
    });
    expect(toast.success).toHaveBeenCalledWith('Registration successful! Please log in.');
    expect(router.goto).toHaveBeenCalledWith('/login');
  });

  it('shows error in DOM on API error (no duplicate toast)', async () => {
    mocks.registerApiV1AuthRegisterPost.mockResolvedValue({
      data: undefined,
      error: { detail: 'Username taken' },
    });
    mocks.mockGetErrorMessage.mockReturnValue('Registration failed. Please try again.');

    await renderRegister();
    await user.type(screen.getByPlaceholderText('Username'), 'taken');
    await user.type(screen.getByPlaceholderText('Email address'), 'e@m.com');
    await user.type(screen.getByPlaceholderText('Password (min. 8 characters)'), 'password123');
    await user.type(screen.getByPlaceholderText('Confirm Password'), 'password123');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText('Registration failed. Please try again.')).toBeInTheDocument();
    });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('disables button and shows "Registering..." during loading', async () => {
    let resolveRegister: (v: unknown) => void;
    mocks.registerApiV1AuthRegisterPost.mockImplementation(
      () => new Promise((r) => { resolveRegister = r; })
    );

    await renderRegister();
    await user.type(screen.getByPlaceholderText('Username'), 'user');
    await user.type(screen.getByPlaceholderText('Email address'), 'e@m.com');
    await user.type(screen.getByPlaceholderText('Password (min. 8 characters)'), 'password123');
    await user.type(screen.getByPlaceholderText('Confirm Password'), 'password123');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => {
      expect(screen.getByText('Registering...')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /registering/i })).toBeDisabled();

    resolveRegister!({ data: {}, error: undefined });
    await waitFor(() => {
      expect(screen.queryByText('Registering...')).not.toBeInTheDocument();
    });
  });

  it('calls updateMetaTags on mount', async () => {
    await renderRegister();
    await waitFor(() => {
      expect(meta.updateMetaTags).toHaveBeenCalledWith('Register', expect.stringContaining('Create a free Integr8sCode account'));
    });
  });
});
