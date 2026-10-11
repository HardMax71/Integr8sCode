import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ApiError } from '#lib/api-error.ts';

const { getErrorMessage } =
    await vi.importActual<typeof import('#lib/api-interceptors.ts')>('#lib/api-interceptors.ts');

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
    ] as [string, unknown, string | undefined, string][])(
        'returns fallback for %s',
        (_label, input, fallback, expected) => {
            expect(getErrorMessage(input, fallback)).toBe(expected);
        },
    );

    it.each([
        ['string error', 'something broke', 'something broke'],
        ['Error instance', new Error('boom'), 'boom'],
        ['object with .detail string', { detail: 'Not found' }, 'Not found'],
        [
            'ValidationError[] with locs',
            {
                detail: [
                    { loc: ['body', 'email'], msg: 'invalid email', type: 'value_error' },
                    { loc: ['body', 'name'], msg: 'required', type: 'value_error' },
                ],
            },
            'email: invalid email, name: required',
        ],
        [
            'ValidationError[] with empty loc',
            {
                detail: [{ loc: [], msg: 'bad', type: 'value_error' }],
            },
            'bad',
        ],
        [
            'ValidationError[] with single loc',
            {
                detail: [{ loc: ['body'], msg: 'Error', type: 'value_error' }],
            },
            'body: Error',
        ],
        ['ApiError with a detail body', new ApiError(404, { detail: 'Script not found' }), 'Script not found'],
        [
            'ApiError for a network failure',
            new ApiError(undefined, new TypeError('Failed to fetch')),
            'Failed to fetch',
        ],
    ] as [string, unknown, string][])('extracts message from %s', (_label, input, expected) => {
        expect(getErrorMessage(input)).toBe(expected);
    });
});

describe('initializeApiInterceptors and showApiError', () => {
    let mockErrorUse: ReturnType<typeof vi.fn>;
    let mockRequestUse: ReturnType<typeof vi.fn>;
    let mockSetConfig: ReturnType<typeof vi.fn>;
    let mockSetQueryErrorHandler: ReturnType<typeof vi.fn>;
    let mockToast: Record<string, ReturnType<typeof vi.fn>>;
    let mockGoto: ReturnType<typeof vi.fn>;
    let mockAuthStore: { isAuthenticated: boolean; csrfToken: string | null; clearAuth: ReturnType<typeof vi.fn> };
    let errorInterceptor: (
        error: unknown,
        response: Response | undefined,
        request: Request | undefined,
        opts: { url?: string },
    ) => unknown;
    let requestInterceptor: (request: Request, opts: unknown) => Request;
    let mod: typeof import('#lib/api-interceptors.ts');
    let FreshApiError: typeof ApiError;

    beforeEach(async () => {
        vi.resetModules();

        mockErrorUse = vi.fn();
        mockRequestUse = vi.fn();
        mockSetConfig = vi.fn();
        mockSetQueryErrorHandler = vi.fn();
        mockToast = { error: vi.fn(), warning: vi.fn() };
        mockGoto = vi.fn();
        mockAuthStore = { isAuthenticated: true, csrfToken: 'csrf-123', clearAuth: vi.fn() };

        vi.doMock('#lib/api/index.ts', () => ({
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
        ({ ApiError: FreshApiError } = await import('#lib/api-error.ts'));
        mod.initializeApiInterceptors();

        errorInterceptor = mockErrorUse.mock.calls[0]![0];
        requestInterceptor = mockRequestUse.mock.calls[0]![0];
        vi.spyOn(console, 'error').mockImplementation(() => {});
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
        it('wraps a failed response in an ApiError with its status and body, without a toast', () => {
            const body = { detail: 'Not found' };
            const result = errorInterceptor(body, { status: 404 } as Response, new Request('https://test/api'), {});

            expect(result).toBeInstanceOf(FreshApiError);
            expect(result).toMatchObject({ status: 404, body });
            expect(mockToast.error).not.toHaveBeenCalled();
        });

        it('wraps a request that got no response in an ApiError without a status', () => {
            const failure = new TypeError('Failed to fetch');
            const result = errorInterceptor(failure, undefined, new Request('https://test/api'), {});

            expect(result).toMatchObject({ status: undefined, body: failure });
        });

        it('passes the error through when the request was never built', () => {
            const buildError = new TypeError('Invalid URL');
            expect(errorInterceptor(buildError, undefined, undefined, { url: '/api/v1/execute' })).toBe(buildError);
        });
    });

    describe('showApiError', () => {
        const apiError = (status: number | undefined, body: unknown = 'some error') => new FreshApiError(status, body);

        it('shows the network error toast when there was no response', () => {
            mod.showApiError(apiError(undefined), false);
            expect(mockToast.error).toHaveBeenCalledWith('Network error. Check your connection.');
        });

        it('ends the session on a 401: clears auth, remembers the page and goes to /login', async () => {
            await vi.advanceTimersByTimeAsync(1500);
            at('/editor', '?tab=1');
            mod.showApiError(apiError(401), false);

            expect(mockAuthStore.clearAuth).toHaveBeenCalled();
            expect(mockToast.warning).toHaveBeenCalledWith('Session expired. Please log in again.');
            expect(sessionStorage.setItem).toHaveBeenCalledWith('redirectAfterLogin', '/editor?tab=1');
            expect(mockGoto).toHaveBeenCalledWith('/login');
        });

        it('does not remember /login as the page to return to', async () => {
            await vi.advanceTimersByTimeAsync(1500);
            vi.mocked(sessionStorage.setItem).mockClear();
            at('/login');
            mod.showApiError(apiError(401), false);
            expect(sessionStorage.setItem).not.toHaveBeenCalledWith('redirectAfterLogin', expect.anything());
        });

        it('just clears auth on a 401 when nobody was signed in', () => {
            mockAuthStore.isAuthenticated = false;
            at('/editor');
            mod.showApiError(apiError(401), false);
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
                mod.showApiError(apiError(status), false);
                mod.showApiError(apiError(status), true);
                expect(mockToast[type]).toHaveBeenCalledTimes(2);
                expect(mockToast[type]).toHaveBeenCalledWith(message);
            },
        );

        it('shows account locked for 423', () => {
            mod.showApiError(apiError(423), true);
            expect(mockToast.warning).toHaveBeenCalledWith(expect.stringContaining('temporarily locked'));
        });

        it('shows the validation errors for 422', () => {
            mod.showApiError(apiError(422, { detail: [{ loc: ['body', 'email'], msg: 'invalid', type: 'x' }] }), false);
            expect(mockToast.error).toHaveBeenCalledWith('Validation error: email: invalid');
        });

        it('shows the detail for any other 4xx', () => {
            mod.showApiError(apiError(409, { detail: 'Username already exists' }), false);
            expect(mockToast.error).toHaveBeenCalledWith('Username already exists');
        });

        it('leaves network errors, 401s and other 4xx to an inline form', () => {
            at('/login');
            mod.showApiError(apiError(undefined), true);
            mod.showApiError(apiError(401), true);
            mod.showApiError(apiError(409, { detail: 'Username already exists' }), true);

            expect(mockToast.error).not.toHaveBeenCalled();
            expect(mockToast.warning).not.toHaveBeenCalled();
            expect(mockAuthStore.clearAuth).not.toHaveBeenCalled();
            expect(mockGoto).not.toHaveBeenCalled();
        });

        it('ignores errors that never reached the server', () => {
            mod.showApiError(new TypeError('Invalid URL'), false);
            expect(mockToast.error).not.toHaveBeenCalled();
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
