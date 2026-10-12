import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { mockApi, renderWithQueryClient, user } from '#test/test-utils.ts';
import { toast } from 'svelte-sonner';
import * as navigation from '$app/navigation';
import { loginApiV1AuthLoginPost, UserRole, type LoginResponse } from '#lib/api/index.ts';
import { queryClient } from '#lib/query-client.ts';
import Login from '#routes/login/+page.svelte';

const mocks = vi.hoisted(() => ({
    mockAuthStore: {
        startSession: vi.fn(),
        isAuthenticated: false,
        user: null,
        verifyAuth: vi.fn(),
    },
}));

vi.mock('#stores/auth.svelte.ts', () => ({ authStore: mocks.mockAuthStore }));

const loginResponse: LoginResponse = { message: 'ok', username: 'testuser', role: UserRole.USER, csrf_token: 'csrf' };

describe('Login', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.mockAuthStore.startSession.mockResolvedValue(undefined);
        mockApi(loginApiV1AuthLoginPost).ok(loginResponse);
    });

    async function submit(username = 'testuser', password = 'pass1234') {
        renderWithQueryClient(Login);
        await user.type(screen.getByPlaceholderText('Username'), username);
        await user.type(screen.getByPlaceholderText('Password'), password);
        await user.click(screen.getByRole('button', { name: /sign in/i }));
    }

    it('renders sign-in form with heading, inputs, button, and register link', () => {
        renderWithQueryClient(Login);
        expect(screen.getByRole('heading', { name: /sign in to your account/i })).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Username')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Password')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /create a new account/i })).toHaveAttribute('href', '/register');
    });

    it('shows auth message from sessionStorage and removes it', async () => {
        sessionStorage.setItem('authMessage', 'Please log in to continue');
        renderWithQueryClient(Login);
        await waitFor(() => {
            expect(toast.info).toHaveBeenCalledWith('Please log in to continue');
        });
        expect(sessionStorage.getItem('authMessage')).toBeNull();
    });

    it('marks both fields as required when submitted empty, and sends nothing', async () => {
        renderWithQueryClient(Login);
        await user.click(screen.getByRole('button', { name: /sign in/i }));

        for (const field of ['Username', 'Password']) {
            const input = screen.getByPlaceholderText(field);
            await waitFor(() => expect(input).toHaveAttribute('aria-invalid', 'true'));
            expect(input).toHaveAccessibleDescription('Required');
        }
        expect(vi.mocked(loginApiV1AuthLoginPost)).not.toHaveBeenCalled();
    });

    it('posts the credentials, starts the session, shows toast, redirects to /editor', async () => {
        await submit();

        await waitFor(() => expect(navigation.goto).toHaveBeenCalledWith('/editor'));
        expect(vi.mocked(loginApiV1AuthLoginPost)).toHaveBeenCalledWith(
            expect.objectContaining({ body: { username: 'testuser', password: 'pass1234' } }),
        );
        expect(mocks.mockAuthStore.startSession).toHaveBeenCalledWith(loginResponse);
        expect(toast.success).toHaveBeenCalledWith('Login successful! Welcome back.');
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
        await submit('u', 'p');

        await waitFor(() => {
            expect(navigation.goto).toHaveBeenCalledWith(expectedNav);
        });
        expect(sessionStorage.getItem('redirectAfterLogin')).toBeNull();
    });

    it('shows the API error inline and opts out of the global toasts', async () => {
        mockApi(loginApiV1AuthLoginPost).err({ detail: 'Invalid credentials' });

        await submit('bad', 'bad');

        await waitFor(() => {
            expect(screen.getByTestId('error-message')).toHaveTextContent('Invalid credentials');
        });
        expect(queryClient.getMutationCache().getAll()[0]?.meta).toEqual({ inlineErrors: true });
        expect(mocks.mockAuthStore.startSession).not.toHaveBeenCalled();
        expect(toast.error).not.toHaveBeenCalled();
        expect(navigation.goto).not.toHaveBeenCalled();
    });

    it('disables button and shows "Logging in..." until the session has started', async () => {
        let finishSession: () => void;
        mocks.mockAuthStore.startSession.mockImplementation(
            () =>
                new Promise<void>((r) => {
                    finishSession = r;
                }),
        );

        await submit('u', 'p');

        await waitFor(() => {
            expect(screen.getByText('Logging in...')).toBeInTheDocument();
        });
        expect(screen.getByRole('button', { name: /logging in/i })).toBeDisabled();

        finishSession!();
        await waitFor(() => {
            expect(screen.queryByText('Logging in...')).not.toBeInTheDocument();
        });
    });

    it('sets the page title', async () => {
        renderWithQueryClient(Login);
        await waitFor(() => expect(document.title).toBe('Login - Integr8sCode'));
    });
});
