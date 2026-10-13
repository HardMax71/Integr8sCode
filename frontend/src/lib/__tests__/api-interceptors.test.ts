import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ErrorResponse } from '#lib/api/index.ts';
import type { Session } from '#stores/auth.svelte.ts';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { captureLogs } from '#test/test-utils.ts';

describe('initializeApiInterceptors and showApiError', () => {
    let mockErrorUse: ReturnType<typeof vi.fn>;
    let mockRequestUse: ReturnType<typeof vi.fn>;
    let mockSetConfig: ReturnType<typeof vi.fn>;
    let mockSetQueryErrorHandler: ReturnType<typeof vi.fn>;
    let mockToast: Record<string, ReturnType<typeof vi.fn>>;
    let mockGoto: ReturnType<typeof vi.fn>;
    let mockAuthStore: { session: Session; clearAuth: ReturnType<typeof vi.fn> };
    let errorInterceptor: (
        error: unknown,
        response: Response | undefined,
        request: Request | undefined,
        opts: { url?: string },
    ) => unknown;
    let requestInterceptor: (request: Request, opts: unknown) => Request;
    let mod: typeof import('#lib/api-interceptors.ts');

    beforeEach(async () => {
        vi.resetModules();

        mockErrorUse = vi.fn();
        mockRequestUse = vi.fn();
        mockSetConfig = vi.fn();
        mockSetQueryErrorHandler = vi.fn();
        mockToast = { error: vi.fn(), warning: vi.fn() };
        mockGoto = vi.fn();
        mockAuthStore = {
            session: { status: 'signed-in', user: fakeUserResponse(), csrfToken: 'csrf-123' },
            clearAuth: vi.fn(),
        };

        vi.doMock('#lib/api/index.ts', async (importOriginal) => ({
            ...(await importOriginal<typeof import('#lib/api/index.ts')>()),
            client: {
                setConfig: mockSetConfig,
                interceptors: {
                    error: { use: mockErrorUse },
                    request: { use: mockRequestUse },
                },
            },
        }));
        vi.doMock('#lib/query-client.ts', () => ({ setQueryErrorHandler: mockSetQueryErrorHandler }));
        vi.doMock('svelte-sonner', () => ({ toast: mockToast }));
        vi.doMock('$app/navigation', () => ({ goto: mockGoto }));
        vi.doMock('#stores/auth.svelte.ts', () => ({ authStore: mockAuthStore }));
        vi.doUnmock('#lib/api-interceptors.ts');

        mod = await import('#lib/api-interceptors.ts');
        mod.initializeApiInterceptors();

        errorInterceptor = mockErrorUse.mock.calls[0]![0];
        requestInterceptor = mockRequestUse.mock.calls[0]![0];
    });

    function at(pathname: string, search = '') {
        Object.defineProperty(window, 'location', {
            value: { pathname, search },
            writable: true,
            configurable: true,
        });
    }

    it('configures the client and hands the query client its error handler', () => {
        expect(mockSetConfig).toHaveBeenCalledWith({ baseUrl: '', credentials: 'include' });
        expect(mockErrorUse).toHaveBeenCalledOnce();
        expect(mockRequestUse).toHaveBeenCalledOnce();
        expect(mockSetQueryErrorHandler).toHaveBeenCalledWith(mod.showApiError);
    });

    describe('error interceptor', () => {
        const request = new Request('https://test/api');

        it('passes an ErrorResponse body through, without a toast', () => {
            const body: ErrorResponse = { status: 404, detail: 'Not found' };
            expect(errorInterceptor(body, { status: 404 } as Response, request, {})).toEqual(body);
            expect(mockToast.error).not.toHaveBeenCalled();
        });

        it('makes any other body, like a proxy error page, an ErrorResponse with the response status', () => {
            const page = '<html>502 Bad Gateway</html>';
            expect(errorInterceptor(page, { status: 502 } as Response, request, {})).toEqual({
                status: 502,
                detail: 'HTTP 502',
            });
        });

        it.each([
            ['got no response', request],
            ['was never built', undefined],
        ])('makes a request that %s a network error with status 0', (_label, req) => {
            expect(
                errorInterceptor(new TypeError('Failed to fetch'), undefined, req, { url: '/api/v1/execute' }),
            ).toEqual({
                status: 0,
                detail: 'Network error. Check your connection.',
            });
        });

        it.each([
            ['debug', 404, { status: 404, detail: 'Not found' }, { status: 404 } as Response],
            ['error', 502, '<html>502 Bad Gateway</html>', { status: 502 } as Response],
            ['error', 0, new TypeError('Failed to fetch'), undefined],
        ] as const)('logs at %s level a request that failed with %i', (level, status, body, response) => {
            const records = captureLogs();
            const failure = errorInterceptor(body, response, request, {}) as ErrorResponse;
            expect(records).toEqual([
                expect.objectContaining({
                    level,
                    category: ['integr8scode', 'api'],
                    message: ['', 'GET', ' ', 'https://test/api', ' failed with ', status, ': ', failure.detail, ''],
                }),
            ]);
        });
    });

    describe('showApiError', () => {
        const failure = (status: number, detail = 'some error'): ErrorResponse => ({ status, detail });
        const network = failure(0, 'Network error. Check your connection.');

        it('shows the network error toast when there was no response', () => {
            mod.showApiError(network, false);
            expect(mockToast.error).toHaveBeenCalledWith('Network error. Check your connection.');
        });

        it('ends the session on a 401: clears auth, remembers the page and goes to /login', async () => {
            await vi.advanceTimersByTimeAsync(1500);
            at('/editor', '?tab=1');
            mod.showApiError(failure(401), false);

            expect(mockAuthStore.clearAuth).toHaveBeenCalled();
            expect(mockToast.warning).toHaveBeenCalledWith('Session expired. Please log in again.');
            expect(sessionStorage.setItem).toHaveBeenCalledWith('redirectAfterLogin', '/editor?tab=1');
            expect(mockGoto).toHaveBeenCalledWith('/login');
        });

        it('does not remember /login as the page to return to', async () => {
            await vi.advanceTimersByTimeAsync(1500);
            vi.mocked(sessionStorage.setItem).mockClear();
            at('/login');
            mod.showApiError(failure(401), false);
            expect(sessionStorage.setItem).not.toHaveBeenCalledWith('redirectAfterLogin', expect.anything());
        });

        it('just clears auth on a 401 when nobody was signed in', () => {
            mockAuthStore.session = { status: 'signed-out' };
            at('/editor');
            mod.showApiError(failure(401), false);
            expect(mockAuthStore.clearAuth).toHaveBeenCalled();
            expect(mockGoto).not.toHaveBeenCalled();
            expect(mockToast.warning).not.toHaveBeenCalled();
        });

        it.each([
            [403, 'error', 'Access denied.'],
            [429, 'warning', 'Too many requests. Please slow down.'],
            [500, 'error', 'Server error. Please try again later.'],
            [503, 'error', 'Server error. Please try again later.'],
        ] as [number, 'error' | 'warning', string][])(
            'shows the %i toast, inline form or not',
            (status, type, message) => {
                mod.showApiError(failure(status), false);
                mod.showApiError(failure(status), true);
                expect(mockToast[type]).toHaveBeenCalledTimes(2);
                expect(mockToast[type]).toHaveBeenCalledWith(message);
            },
        );

        it('shows account locked for 423', () => {
            mod.showApiError(failure(423), true);
            expect(mockToast.warning).toHaveBeenCalledWith(expect.stringContaining('temporarily locked'));
        });

        it('shows the validation errors for 422', () => {
            mod.showApiError(failure(422, 'email: value is not a valid email address'), false);
            expect(mockToast.error).toHaveBeenCalledWith('Validation error: email: value is not a valid email address');
        });

        it('shows the detail for any other 4xx', () => {
            mod.showApiError(failure(409, 'Username already exists'), false);
            expect(mockToast.error).toHaveBeenCalledWith('Username already exists');
        });

        it('leaves network errors, 401s and other 4xx to an inline form', () => {
            at('/login');
            mod.showApiError(network, true);
            mod.showApiError(failure(401), true);
            mod.showApiError(failure(409, 'Username already exists'), true);

            expect(mockToast.error).not.toHaveBeenCalled();
            expect(mockToast.warning).not.toHaveBeenCalled();
            expect(mockAuthStore.clearAuth).not.toHaveBeenCalled();
            expect(mockGoto).not.toHaveBeenCalled();
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

        it('skips header when signed out', () => {
            mockAuthStore.session = { status: 'signed-out' };
            const request = new Request('https://test/api', { method: 'POST' });
            const result = requestInterceptor(request, {});
            expect(result.headers.get('X-CSRF-Token')).toBeNull();
        });
    });
});
