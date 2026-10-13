import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { mockApi, renderWithQueryClient, user } from '#test/test-utils.ts';
import { toast } from 'svelte-sonner';
import * as navigation from '$app/navigation';
import { match } from '$app/paths';
import { loginApiV1AuthLoginPost, UserRole, type LoginResponse } from '#lib/api/index.ts';
import { queryClient } from '#lib/query-client.ts';
import { page } from '#test/page.svelte.ts';
import Login from '#routes/login/+page.svelte';

const loginResponse: LoginResponse = { message: 'ok', username: 'testuser', role: UserRole.USER, csrf_token: 'csrf' };

describe('Login', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        page.url = new URL('https://localhost/login');
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

    it('posts the credentials, shows a toast and goes to /editor with the layout data reloaded', async () => {
        await submit();

        await waitFor(() => expect(navigation.goto).toHaveBeenCalledWith('/editor', { refreshAll: true }));
        expect(vi.mocked(loginApiV1AuthLoginPost)).toHaveBeenCalledWith(
            expect.objectContaining({ body: { username: 'testuser', password: 'pass1234' } }),
        );
        expect(toast.success).toHaveBeenCalledWith('Login successful! Welcome back.');
    });

    it.each([
        { saved: '/settings', route: { id: '/(auth)/settings', params: {} }, goesTo: '/settings' },
        { saved: '/admin/users', route: { id: '/admin/users', params: {} }, goesTo: '/admin/users' },
    ] as const)('goes back to $saved, a page of the app named in ?redirect', async ({ saved, route, goesTo }) => {
        page.url = new URL(`https://localhost/login?${new URLSearchParams({ redirect: saved })}`);
        vi.mocked(match).mockResolvedValue(route);
        await submit('u', 'p');

        await waitFor(() => expect(navigation.goto).toHaveBeenCalledWith(goesTo, { refreshAll: true }));
        expect(match).toHaveBeenCalledWith(saved);
    });

    it('goes to the editor when ?redirect names no page of the app', async () => {
        page.url = new URL(`https://localhost/login?${new URLSearchParams({ redirect: '//evil.com' })}`);
        vi.mocked(match).mockResolvedValue(null);
        await submit('u', 'p');

        await waitFor(() => expect(navigation.goto).toHaveBeenCalledWith('/editor', { refreshAll: true }));
        expect(match).toHaveBeenCalledWith('//evil.com');
    });

    it('goes to the editor without a ?redirect', async () => {
        vi.mocked(match).mockResolvedValue({ id: '/(auth)/editor', params: {} });
        await submit('u', 'p');

        await waitFor(() => expect(navigation.goto).toHaveBeenCalledWith('/editor', { refreshAll: true }));
        expect(match).toHaveBeenCalledWith('/editor');
    });

    it('shows the API error inline and opts out of the global toasts', async () => {
        mockApi(loginApiV1AuthLoginPost).err({ status: 401, detail: 'Invalid credentials' });

        await submit('bad', 'bad');

        await waitFor(() => {
            expect(screen.getByTestId('error-message')).toHaveTextContent('Invalid credentials');
        });
        expect(queryClient.getMutationCache().getAll()[0]?.meta).toEqual({ inlineErrors: true });
        expect(toast.error).not.toHaveBeenCalled();
        expect(navigation.goto).not.toHaveBeenCalled();
    });

    it('disables button and shows "Logging in..." until the signed-in page has loaded', async () => {
        let finishSession: () => void;
        vi.mocked(navigation.goto).mockImplementation(
            () =>
                new Promise<void>((r) => {
                    finishSession = r;
                }),
        );

        await submit('u', 'p');

        await waitFor(() => expect(navigation.goto).toHaveBeenCalled());
        expect(screen.getByText('Logging in...')).toBeInTheDocument();
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
