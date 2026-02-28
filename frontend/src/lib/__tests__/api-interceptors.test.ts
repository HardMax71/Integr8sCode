import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getErrorMessage, unwrap, unwrapOr } from '$lib/api-interceptors';

describe('getErrorMessage', () => {
    it.each([
        ['null', null, undefined, 'An error occurred'],
        ['undefined', undefined, undefined, 'An error occurred'],
        ['zero', 0, undefined, 'An error occurred'],
        ['empty string', '', undefined, 'An error occurred'],
        ['null with custom fallback', null, 'custom', 'custom'],
        ['number', 42, undefined, 'An error occurred'],
        ['boolean', true, undefined, 'An error occurred'],
        ['object without detail/message', { foo: 'bar' }, undefined, 'An error occurred'],
    ] as [string, unknown, string | undefined, string][])('returns fallback for %s', (_label, input, fallback, expected) => {
        expect(getErrorMessage(input, fallback)).toBe(expected);
    });

    it.each([
        ['string error', 'something broke', 'something broke'],
        ['Error instance', new Error('boom'), 'boom'],
        ['object with .detail string', { detail: 'Not found' }, 'Not found'],
        ['ValidationError[] with locs', {
            detail: [
                { loc: ['body', 'email'], msg: 'invalid email', type: 'value_error' },
                { loc: ['body', 'name'], msg: 'required', type: 'value_error' },
            ],
        }, 'email: invalid email, name: required'],
        ['ValidationError[] with empty loc', {
            detail: [{ loc: [], msg: 'bad', type: 'value_error' }],
        }, 'bad'],
        ['ValidationError[] with single loc', {
            detail: [{ loc: ['body'], msg: 'Error', type: 'value_error' }],
        }, 'body: Error'],
    ] as [string, unknown, string][])('extracts message from %s', (_label, input, expected) => {
        expect(getErrorMessage(input)).toBe(expected);
    });
});

describe('unwrap', () => {
    it.each([
        ['number', { data: 42 }, 42],
        ['zero', { data: 0 }, 0],
        ['empty string', { data: '' }, ''],
        ['false', { data: false }, false],
    ] as [string, { data: unknown }, unknown][])('returns data for %s', (_label, result, expected) => {
        expect(unwrap(result)).toBe(expected);
    });

    it.each([
        ['error present', { data: 42, error: new Error('fail') }],
        ['data undefined', {}],
    ] as [string, { data?: unknown; error?: unknown }][])('throws when %s', (_label, result) => {
        expect(() => unwrap(result)).toThrow();
    });
});

describe('unwrapOr', () => {
    it.each([
        ['data present', { data: 'value' }, 'fb', 'value'],
        ['data is 0', { data: 0 }, 99, 0],
        ['data is empty string', { data: '' }, 'fb', ''],
        ['error present', { data: 'v', error: new Error() }, 'fb', 'fb'],
        ['data undefined', {}, 'fb', 'fb'],
    ] as [string, { data?: unknown; error?: unknown }, unknown, unknown][])('returns correct value when %s', (_label, result, fallback, expected) => {
        expect(unwrapOr(result, fallback)).toBe(expected);
    });
});

describe('initializeApiInterceptors', () => {
    let mockErrorUse: ReturnType<typeof vi.fn>;
    let mockRequestUse: ReturnType<typeof vi.fn>;
    let mockSetConfig: ReturnType<typeof vi.fn>;
    let mockToast: Record<string, ReturnType<typeof vi.fn>>;
    let mockGoto: ReturnType<typeof vi.fn>;
    let mockAuthStore: { isAuthenticated: boolean; csrfToken: string | null; clearAuth: ReturnType<typeof vi.fn> };
    let errorInterceptor: (error: unknown, response: Response | undefined, request: Request, opts: unknown) => unknown;
    let requestInterceptor: (request: Request, opts: unknown) => Request;

    beforeEach(async () => {
        vi.resetModules();

        mockErrorUse = vi.fn();
        mockRequestUse = vi.fn();
        mockSetConfig = vi.fn();
        mockToast = { error: vi.fn(), warning: vi.fn() };
        mockGoto = vi.fn();
        mockAuthStore = { isAuthenticated: true, csrfToken: 'csrf-123', clearAuth: vi.fn() };

        vi.doMock('$lib/api/client.gen', () => ({
            client: {
                setConfig: mockSetConfig,
                interceptors: {
                    error: { use: mockErrorUse },
                    request: { use: mockRequestUse },
                },
            },
        }));
        vi.doMock('svelte-sonner', () => ({ toast: mockToast }));
        vi.doMock('@mateothegreat/svelte5-router', () => ({ goto: mockGoto }));
        vi.doMock('$stores/auth.svelte', () => ({ authStore: mockAuthStore }));

        const mod = await import('$lib/api-interceptors');
        mod.initializeApiInterceptors();

        errorInterceptor = mockErrorUse.mock.calls[0]![0];
        requestInterceptor = mockRequestUse.mock.calls[0]![0];
    });

    it('calls client.setConfig with baseUrl and credentials', () => {
        expect(mockSetConfig).toHaveBeenCalledWith({ baseUrl: '', credentials: 'include' });
    });

    it('registers error interceptor', () => {
        expect(mockErrorUse).toHaveBeenCalledOnce();
    });

    it('registers request interceptor', () => {
        expect(mockRequestUse).toHaveBeenCalledOnce();
    });

    describe('error interceptor: handleErrorStatus', () => {
        function callError(status: number | undefined, url = 'https://test/api/v1/execute') {
            const response = status ? { status } as Response : undefined;
            const request = new Request(url);
            vi.spyOn(console, 'error').mockImplementation(() => {});
            return errorInterceptor('some error', response, request, {});
        }

        it('shows network error toast when status undefined', () => {
            callError(undefined);
            expect(mockToast.error).toHaveBeenCalledWith('Network error. Check your connection.');
        });

        it('skips network error toast for auth endpoints', () => {
            callError(undefined, 'https://test/api/v1/auth/login');
            expect(mockToast.error).not.toHaveBeenCalled();
        });

        it('handles 401 - clears auth and redirects to /login', () => {
            Object.defineProperty(window, 'location', {
                value: { pathname: '/editor', search: '' },
                writable: true,
                configurable: true,
            });
            callError(401);
            expect(mockAuthStore.clearAuth).toHaveBeenCalled();
            expect(mockToast.warning).toHaveBeenCalledWith('Session expired. Please log in again.');
            expect(mockGoto).toHaveBeenCalledWith('/login');
        });

        it('stores redirectAfterLogin in sessionStorage for non-login paths', () => {
            Object.defineProperty(window, 'location', {
                value: { pathname: '/editor', search: '?tab=1' },
                writable: true,
                configurable: true,
            });
            callError(401);
            expect(sessionStorage.setItem).toHaveBeenCalledWith('redirectAfterLogin', '/editor?tab=1');
        });

        it('does not store redirectAfterLogin for /login path', async () => {
            // Wait for isHandling401 debounce from prior tests to clear
            await vi.advanceTimersByTimeAsync(1500);
            vi.mocked(sessionStorage.setItem).mockClear();
            Object.defineProperty(window, 'location', {
                value: { pathname: '/login', search: '' },
                writable: true,
                configurable: true,
            });
            callError(401);
            expect(sessionStorage.setItem).not.toHaveBeenCalledWith('redirectAfterLogin', expect.anything());
        });

        it('401 on auth endpoint is a no-op', () => {
            callError(401, 'https://test/api/v1/auth/login');
            expect(mockAuthStore.clearAuth).not.toHaveBeenCalled();
            expect(mockGoto).not.toHaveBeenCalled();
        });

        it('401 when not authenticated just clears auth without redirect', () => {
            mockAuthStore.isAuthenticated = false;
            Object.defineProperty(window, 'location', {
                value: { pathname: '/editor', search: '' },
                writable: true,
                configurable: true,
            });
            callError(401);
            expect(mockAuthStore.clearAuth).toHaveBeenCalled();
            expect(mockGoto).not.toHaveBeenCalled();
        });

        it.each([
            [403, 'error', 'Access denied.'],
            [429, 'warning', 'Too many requests. Please slow down.'],
            [500, 'error', 'Server error. Please try again later.'],
            [503, 'error', 'Server error. Please try again later.'],
        ] as [number, 'error' | 'warning', string][])('shows correct toast for %i status', (status, toastType, message) => {
            callError(status);
            expect(mockToast[toastType]).toHaveBeenCalledWith(message);
        });

        it('shows account locked for 423', () => {
            callError(423);
            expect(mockToast.warning).toHaveBeenCalledWith(expect.stringContaining('temporarily locked'));
        });

        it('shows validation error for 422', () => {
            const response = { status: 422 } as Response;
            const request = new Request('https://test/api/v1/execute');
            vi.spyOn(console, 'error').mockImplementation(() => {});
            errorInterceptor({ detail: 'bad field' }, response, request, {});
            expect(mockToast.error).toHaveBeenCalledWith(expect.stringContaining('Validation error'));
        });

        it('shows generic error for unhandled non-auth status', () => {
            callError(418);
            expect(mockToast.error).toHaveBeenCalledWith(expect.any(String));
        });

        it('returns the error object', () => {
            vi.spyOn(console, 'error').mockImplementation(() => {});
            const result = errorInterceptor('my-error', { status: 403 } as Response, new Request('https://test/api'), {});
            expect(result).toBe('my-error');
        });
    });

    describe('CSRF request interceptor', () => {
        it.each(['POST', 'PUT', 'DELETE'])('adds X-CSRF-Token header for %s requests', (method) => {
            const request = new Request('https://test/api', { method });
            const result = requestInterceptor(request, {});
            expect(result.headers.get('X-CSRF-Token')).toBe('csrf-123');
        });

        it('skips header for GET requests', () => {
            const request = new Request('https://test/api', { method: 'GET' });
            const result = requestInterceptor(request, {});
            expect(result.headers.get('X-CSRF-Token')).toBeNull();
        });

        it('skips header when no CSRF token available', () => {
            mockAuthStore.csrfToken = null;
            const request = new Request('https://test/api', { method: 'POST' });
            const result = requestInterceptor(request, {});
            expect(result.headers.get('X-CSRF-Token')).toBeNull();
        });
    });
});
