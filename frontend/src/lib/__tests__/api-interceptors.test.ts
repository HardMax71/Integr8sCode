import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ErrorResponse } from '#lib/api/index.ts';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { captureLogs } from '#test/test-utils.ts';
import { page } from '#test/page.svelte.ts';

function failure(status: number, detail = 'some error'): ErrorResponse {
    return { status, detail };
}

describe('initializeApiInterceptors and showApiError', () => {
    let mockErrorUse: ReturnType<typeof vi.fn>;
    let mockRequestUse: ReturnType<typeof vi.fn>;
    let mockSetConfig: ReturnType<typeof vi.fn>;
    let mockSetQueryErrorHandler: ReturnType<typeof vi.fn>;
    let mockToast: Record<string, ReturnType<typeof vi.fn>>;
    let mockRefreshAll: ReturnType<typeof vi.fn>;
    let mockClear: ReturnType<typeof vi.fn>;
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
        mockRefreshAll = vi.fn();
        mockClear = vi.fn();
        page.data.user = fakeUserResponse();

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
        vi.doMock('#lib/query-client.ts', () => ({
            setQueryErrorHandler: mockSetQueryErrorHandler,
            queryClient: { clear: mockClear },
        }));
        vi.doMock('svelte-sonner', () => ({ toast: mockToast }));
        vi.doMock('$app/navigation', () => ({ refreshAll: mockRefreshAll }));
        // resetModules would otherwise hand the module a fresh stand-in, not the one this test sets
        vi.doMock('$app/state', () => ({ page }));
        vi.doUnmock('#lib/api-interceptors.ts');

        mod = await import('#lib/api-interceptors.ts');
        mod.initializeApiInterceptors();

        errorInterceptor = mockErrorUse.mock.calls[0]![0];
        requestInterceptor = mockRequestUse.mock.calls[0]![0];
    });

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
        const network = failure(0, 'Network error. Check your connection.');

        it('shows the network error toast when there was no response', () => {
            mod.showApiError(network, false);
            expect(mockToast.error).toHaveBeenCalledWith('Network error. Check your connection.');
        });

        it('ends an expired session: one toast, an empty cache, and the layout data loaded again', () => {
            mod.showApiError(failure(401), false);

            expect(mockToast.warning).toHaveBeenCalledWith('Session expired. Please log in again.', {
                id: 'session-expired',
            });
            expect(mockClear).toHaveBeenCalled();
            expect(mockRefreshAll).toHaveBeenCalled();
        });

        it("leaves a visitor's 401 alone, since there's no session to end", () => {
            page.data.user = null;
            mod.showApiError(failure(401), false);
            expect(mockToast.warning).not.toHaveBeenCalled();
            expect(mockClear).not.toHaveBeenCalled();
            expect(mockRefreshAll).not.toHaveBeenCalled();
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
            mod.showApiError(network, true);
            mod.showApiError(failure(401), true);
            mod.showApiError(failure(409, 'Username already exists'), true);

            expect(mockToast.error).not.toHaveBeenCalled();
            expect(mockToast.warning).not.toHaveBeenCalled();
            expect(mockClear).not.toHaveBeenCalled();
            expect(mockRefreshAll).not.toHaveBeenCalled();
        });
    });

    describe('CSRF request interceptor', () => {
        beforeEach(() => {
            document.cookie = 'csrf_token=csrf-123';
        });

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

        it('skips header without a csrf_token cookie, as when signed out', () => {
            document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
            const request = new Request('https://test/api', { method: 'POST' });
            const result = requestInterceptor(request, {});
            expect(result.headers.get('X-CSRF-Token')).toBeNull();
        });
    });
});
