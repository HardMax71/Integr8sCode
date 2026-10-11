import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/svelte';
import { user, mockApi, renderWithQueryClient } from '#test/test-utils.ts';
import { toast } from 'svelte-sonner';
import * as navigation from '$app/navigation';
import Register from '#routes/register/+page.svelte';

import { registerApiV1AuthRegisterPost } from '#lib/api/index.ts';
import { queryClient } from '#lib/query-client.ts';

describe('Register', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockApi(registerApiV1AuthRegisterPost).ok({});
    });

    function renderRegister() {
        return renderWithQueryClient(Register);
    }

    it('renders form with 4 inputs, submit button, and login link', async () => {
        await renderRegister();
        expect(screen.getByRole('heading', { name: /create a new account/i })).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Username')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Email address')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Password (min. 8 characters)')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Confirm Password')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /sign in to your existing account/i })).toHaveAttribute(
            'href',
            '/login',
        );
    });

    it.each([
        {
            name: 'mismatched passwords',
            password: 'password1',
            confirmPassword: 'password2',
            field: 'Confirm Password',
            expectedError: 'Passwords do not match',
        },
        {
            name: 'a short password',
            password: 'short',
            confirmPassword: 'short',
            field: 'Password (min. 8 characters)',
            expectedError: 'Must be at least 8 characters',
        },
    ])('shows $name under the field and sends nothing', async ({ password, confirmPassword, field, expectedError }) => {
        await renderRegister();
        await user.type(screen.getByPlaceholderText('Username'), 'testuser');
        await user.type(screen.getByPlaceholderText('Email address'), 'test@email.com');
        await user.type(screen.getByPlaceholderText('Password (min. 8 characters)'), password);
        await user.type(screen.getByPlaceholderText('Confirm Password'), confirmPassword);
        await user.click(screen.getByRole('button', { name: /create account/i }));

        const input = screen.getByPlaceholderText(field);
        await waitFor(() => expect(input).toHaveAttribute('aria-invalid', 'true'));
        expect(input).toHaveAccessibleDescription(expectedError);
        expect(toast.error).not.toHaveBeenCalled();
        expect(toast.warning).not.toHaveBeenCalled();
        expect(vi.mocked(registerApiV1AuthRegisterPost)).not.toHaveBeenCalled();
    });

    it('marks an invalid email with the reason', async () => {
        await renderRegister();
        await user.type(screen.getByPlaceholderText('Email address'), 'not-an-email');
        await user.click(screen.getByRole('button', { name: /create account/i }));

        const input = screen.getByPlaceholderText('Email address');
        await waitFor(() => expect(input).toHaveAccessibleDescription('Must be a valid email'));
    });

    it('calls API with correct payload, shows toast, and redirects on success', async () => {
        await renderRegister();
        await user.type(screen.getByPlaceholderText('Username'), 'newuser');
        await user.type(screen.getByPlaceholderText('Email address'), 'new@email.com');
        await user.type(screen.getByPlaceholderText('Password (min. 8 characters)'), 'securepass');
        await user.type(screen.getByPlaceholderText('Confirm Password'), 'securepass');
        await user.click(screen.getByRole('button', { name: /create account/i }));

        await waitFor(() => {
            expect(vi.mocked(registerApiV1AuthRegisterPost)).toHaveBeenCalledWith(
                expect.objectContaining({
                    body: { username: 'newuser', email: 'new@email.com', password: 'securepass' },
                }),
            );
        });
        expect(toast.success).toHaveBeenCalledWith('Registration successful! Please log in.');
        expect(navigation.goto).toHaveBeenCalledWith('/login');
    });

    it('shows the API error inline and opts out of the global toasts', async () => {
        mockApi(registerApiV1AuthRegisterPost).err({ detail: 'Username taken' });

        await renderRegister();
        await user.type(screen.getByPlaceholderText('Username'), 'taken');
        await user.type(screen.getByPlaceholderText('Email address'), 'e@m.com');
        await user.type(screen.getByPlaceholderText('Password (min. 8 characters)'), 'password123');
        await user.type(screen.getByPlaceholderText('Confirm Password'), 'password123');
        await user.click(screen.getByRole('button', { name: /create account/i }));

        await waitFor(() => {
            expect(screen.getByTestId('error-message')).toHaveTextContent('Username taken');
        });
        expect(queryClient.getMutationCache().getAll()[0]?.meta).toEqual({ inlineErrors: true });
        expect(toast.error).not.toHaveBeenCalled();
        expect(navigation.goto).not.toHaveBeenCalled();
    });

    it('disables button and shows "Registering..." during loading', async () => {
        let resolveRegister: (v: unknown) => void;
        mockApi(registerApiV1AuthRegisterPost).mock.mockImplementation(
            () =>
                new Promise((r) => {
                    resolveRegister = r;
                }),
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

        resolveRegister!({ data: { user_id: 'u1' }, error: undefined });
        await waitFor(() => {
            expect(screen.queryByText('Registering...')).not.toBeInTheDocument();
        });
    });

    it('sets the page title', async () => {
        await renderRegister();
        await waitFor(() => expect(document.title).toBe('Register - Integr8sCode'));
    });
});
