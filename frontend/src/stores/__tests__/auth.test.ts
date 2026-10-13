import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { suppressConsoleWarn } from '#test/test-utils.ts';
import { fakeUserResponse } from '#lib/api/@faker-js/faker.gen.ts';
import { UserRole, type ErrorResponse, type LoginResponse, type UserResponse } from '#lib/api/index.ts';

const mockGetProfileApi = vi.fn();

// The generated query options import the SDK from sdk.gen, so the mock goes there
vi.mock('#lib/api/sdk.gen.ts', async (importOriginal) => ({
    ...(await importOriginal<typeof import('#lib/api/sdk.gen.ts')>()),
    getCurrentUserProfileApiV1AuthMeGet: (...args: unknown[]) => mockGetProfileApi(...args),
}));

const PROFILE_RESPONSE = { ...fakeUserResponse(), user_id: 'user-123' };

const LOGIN_RESPONSE: LoginResponse = {
    message: 'ok',
    username: 'testuser',
    role: UserRole.USER,
    csrf_token: 'new-csrf-token',
};

type Failure = 'unauthorized' | 'server' | 'network';

function persistedState(overrides: Record<string, unknown> = {}) {
    return JSON.stringify({
        isAuthenticated: true,
        user: PROFILE_RESPONSE,
        csrfToken: 'csrf-token',
        timestamp: Date.now(),
        ...overrides,
    });
}

describe('auth store', () => {
    let sessionStorageData: Record<string, string> = {};

    beforeEach(() => {
        sessionStorageData = {};
        vi.mocked(sessionStorage.getItem).mockImplementation((key: string) => sessionStorageData[key] ?? null);
        vi.mocked(sessionStorage.setItem).mockImplementation((key: string, value: string) => {
            sessionStorageData[key] = value;
        });
        vi.mocked(sessionStorage.removeItem).mockImplementation((key: string) => {
            delete sessionStorageData[key];
        });

        mockGetProfileApi.mockReset();
        vi.resetModules();
    });

    afterEach(() => {
        vi.clearAllMocks();
    });

    // A fresh store per test, with the query client from the same module graph
    async function load() {
        const [{ authStore }, { queryClient }] = await Promise.all([
            import('#stores/auth.svelte.ts'),
            import('#lib/query-client.ts'),
        ]);
        const fail = (failure: Failure): ErrorResponse =>
            failure === 'network'
                ? { status: 0, detail: 'Network error. Check your connection.' }
                : { status: failure === 'unauthorized' ? 401 : 500, detail: failure };
        return { authStore, queryClient, fail };
    }

    function profileOk(profile: UserResponse = PROFILE_RESPONSE) {
        mockGetProfileApi.mockResolvedValue({ data: profile });
    }

    describe('initial state', () => {
        it('starts signed out with nothing persisted', async () => {
            const { authStore } = await load();
            expect(authStore.isAuthenticated).toBe(null);
            expect(authStore.user).toBe(null);
        });

        it('restores auth state from sessionStorage', async () => {
            sessionStorageData['authState'] = persistedState({ csrfToken: 'test-token' });

            const { authStore } = await load();

            expect(authStore.isAuthenticated).toBe(true);
            expect(authStore.user).toEqual(PROFILE_RESPONSE);
            expect(authStore.csrfToken).toBe('test-token');
        });

        it('drops a persisted state that is not a valid session', async () => {
            sessionStorageData['authState'] = persistedState({ user: { username: 'testuser' } });

            const { authStore } = await load();

            expect(authStore.isAuthenticated).toBe(null);
            expect(authStore.user).toBe(null);
            expect(sessionStorageData['authState']).toBeUndefined();
        });
    });

    describe('startSession', () => {
        it('loads the profile before it resolves and persists the session', async () => {
            profileOk();
            const { authStore } = await load();

            await authStore.startSession(LOGIN_RESPONSE);

            expect(mockGetProfileApi).toHaveBeenCalledTimes(1);
            expect(authStore.isAuthenticated).toBe(true);
            expect(authStore.user).toEqual(PROFILE_RESPONSE);
            expect(JSON.parse(sessionStorageData['authState']!)).toMatchObject({
                isAuthenticated: true,
                user: PROFILE_RESPONSE,
            });
        });

        it('ends the session when the profile check gets a 401', async () => {
            const { authStore, fail } = await load();
            mockGetProfileApi.mockRejectedValue(fail('unauthorized'));

            await authStore.startSession(LOGIN_RESPONSE);

            expect(authStore.isAuthenticated).toBe(false);
            expect(sessionStorageData['authState']).toBeUndefined();
        });

        it('keeps the session from the login response when the profile check hits a network error', async () => {
            const restoreConsole = suppressConsoleWarn();
            const { authStore, fail } = await load();
            mockGetProfileApi.mockRejectedValue(fail('network'));

            await authStore.startSession(LOGIN_RESPONSE);

            expect(authStore.isAuthenticated).toBe(true);
            expect(authStore.csrfToken).toBe('new-csrf-token');
            expect(authStore.user).toBe(null);
            restoreConsole();
        });
    });

    describe('clearAuth', () => {
        it('clears the state, the persisted copy and every cached query', async () => {
            profileOk();
            const { authStore, queryClient } = await load();
            await authStore.verifyAuth(true);
            queryClient.setQueryData(['anything'], 1);

            authStore.clearAuth();

            expect(authStore.isAuthenticated).toBe(false);
            expect(authStore.user).toBe(null);
            expect(sessionStorage.removeItem).toHaveBeenCalledWith('authState');
            expect(queryClient.getQueryCache().getAll()).toEqual([]);
        });
    });

    describe('verifyAuth', () => {
        it('returns true and stores the profile when verification succeeds', async () => {
            profileOk();
            const { authStore } = await load();

            expect(await authStore.verifyAuth(true)).toBe(true);
            expect(authStore.user).toEqual(PROFILE_RESPONSE);
        });

        it('returns false and clears state on a 401', async () => {
            const { authStore, fail } = await load();
            mockGetProfileApi.mockRejectedValue(fail('unauthorized'));

            expect(await authStore.verifyAuth(true)).toBe(false);
            expect(authStore.isAuthenticated).toBe(false);
            expect(sessionStorage.removeItem).toHaveBeenCalledWith('authState');
        });

        it('answers from the cache for 30 seconds unless forced', async () => {
            profileOk();
            const { authStore } = await load();

            await authStore.verifyAuth(true);
            await authStore.verifyAuth();
            expect(mockGetProfileApi).toHaveBeenCalledTimes(1);

            await authStore.verifyAuth(true);
            expect(mockGetProfileApi).toHaveBeenCalledTimes(2);

            await vi.advanceTimersByTimeAsync(30_001);
            await authStore.verifyAuth();
            expect(mockGetProfileApi).toHaveBeenCalledTimes(3);
        });

        it('shares one request between checks made at the same time', async () => {
            profileOk();
            const { authStore } = await load();

            const results = await Promise.all([authStore.verifyAuth(true), authStore.verifyAuth(true)]);

            expect(results).toEqual([true, true]);
            expect(mockGetProfileApi).toHaveBeenCalledTimes(1);
        });

        it.each(['network', 'server'] as const)(
            'keeps the cached state on a %s error (offline-first)',
            async (failure) => {
                const restoreConsole = suppressConsoleWarn();
                profileOk();
                const { authStore, fail } = await load();
                expect(await authStore.verifyAuth(true)).toBe(true);

                mockGetProfileApi.mockRejectedValue(fail(failure));

                expect(await authStore.verifyAuth(true)).toBe(true);
                expect(authStore.isAuthenticated).toBe(true);
                expect(authStore.user).toEqual(PROFILE_RESPONSE);
                expect(sessionStorage.removeItem).not.toHaveBeenCalled();
                restoreConsole();
            },
        );

        it('returns false without clearing state on a network error with nothing cached', async () => {
            const restoreConsole = suppressConsoleWarn();
            const { authStore, fail } = await load();
            mockGetProfileApi.mockRejectedValue(fail('network'));

            expect(await authStore.verifyAuth(true)).toBe(false);
            expect(authStore.isAuthenticated).toBe(null);
            expect(sessionStorage.removeItem).not.toHaveBeenCalled();
            restoreConsole();
        });
    });

    describe('initialize', () => {
        it('returns false when no persisted auth and verification fails', async () => {
            const { authStore, fail } = await load();
            mockGetProfileApi.mockRejectedValue(fail('unauthorized'));

            expect(await authStore.initialize()).toBe(false);
        });

        it('returns true when no persisted auth but verification succeeds', async () => {
            profileOk();
            const { authStore } = await load();

            expect(await authStore.initialize()).toBe(true);
            expect(authStore.isAuthenticated).toBe(true);
        });

        it('only initializes once, even when called concurrently', async () => {
            profileOk();
            const { authStore } = await load();

            const results = await Promise.all([authStore.initialize(), authStore.initialize(), authStore.initialize()]);
            await authStore.initialize();

            expect(results).toEqual([true, true, true]);
            expect(mockGetProfileApi).toHaveBeenCalledTimes(1);
        });

        it('restores from persisted auth and verifies', async () => {
            const admin = { ...fakeUserResponse(), user_id: 'user-123', role: UserRole.ADMIN };
            sessionStorageData['authState'] = persistedState({ user: admin });
            profileOk(admin);
            const { authStore } = await load();

            expect(await authStore.initialize()).toBe(true);
            expect(authStore.isAuthenticated).toBe(true);
            expect(authStore.user?.role).toBe(UserRole.ADMIN);
        });

        it('clears auth when persisted auth verification gets a 401', async () => {
            sessionStorageData['authState'] = persistedState();
            const { authStore, fail } = await load();
            mockGetProfileApi.mockRejectedValue(fail('unauthorized'));

            expect(await authStore.initialize()).toBe(false);
            expect(authStore.isAuthenticated).toBe(false);
            expect(sessionStorageData['authState']).toBeUndefined();
        });

        it.each([
            ['keeps recent auth', 2, true],
            ['clears stale auth', 10, false],
        ])('%s on a network error (%i minutes old)', async (_label, minutes, kept) => {
            const restoreConsole = suppressConsoleWarn();
            sessionStorageData['authState'] = persistedState({ timestamp: Date.now() - minutes * 60 * 1000 });
            const { authStore, fail } = await load();
            mockGetProfileApi.mockRejectedValue(fail('network'));

            expect(await authStore.initialize()).toBe(kept);
            expect(authStore.isAuthenticated).toBe(kept);
            expect(sessionStorageData['authState'] !== undefined).toBe(kept);
            restoreConsole();
        });
    });

    describe('waitForInit', () => {
        it('returns immediately if already initialized', async () => {
            profileOk();
            const { authStore } = await load();
            await authStore.initialize();

            expect(await authStore.waitForInit()).toBe(true);
            expect(mockGetProfileApi).toHaveBeenCalledTimes(1);
        });

        it('initializes if not started', async () => {
            profileOk();
            const { authStore } = await load();

            expect(await authStore.waitForInit()).toBe(true);
            expect(mockGetProfileApi).toHaveBeenCalled();
        });
    });
});
