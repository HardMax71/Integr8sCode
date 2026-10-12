import * as z from 'zod/mini';
import {
    getCurrentUserProfileApiV1AuthMeGetOptions,
    getCurrentUserProfileApiV1AuthMeGetQueryKey,
    zUserResponse,
    type LoginResponse,
    type UserResponse,
} from '#lib/api/index.ts';
import { ApiError } from '#lib/api-error.ts';
import { queryClient } from '#lib/query-client.ts';
import { logger } from '#lib/logger.ts';

const log = logger.withTag('Auth');

// --8<-- [start:AuthState]
const zSession = z.object({
    isAuthenticated: z.boolean(),
    user: z.nullable(zUserResponse),
    csrfToken: z.nullable(z.string()),
    timestamp: z.number(),
});
// --8<-- [end:AuthState]

type Session = z.infer<typeof zSession>;

export function getPersistedAuthState(): Session | null {
    if (typeof window === 'undefined') return null;
    try {
        const data = sessionStorage.getItem('authState');
        if (!data) return null;
        const session = zSession.safeParse(JSON.parse(data));
        if (session.success) return session.data;
        sessionStorage.removeItem('authState');
        return null;
    } catch {
        return null;
    }
}

function persistAuthState(session: Omit<Session, 'timestamp'> | null) {
    if (typeof window === 'undefined') return;
    if (!session?.isAuthenticated) {
        sessionStorage.removeItem('authState');
        return;
    }
    sessionStorage.setItem('authState', JSON.stringify({ ...session, timestamp: Date.now() }));
}

const persisted = getPersistedAuthState();

const VERIFY_STALE_MS = 30_000;
const STALE_AUTH_THRESHOLD = 5 * 60 * 1000;

class AuthStore {
    isAuthenticated = $state<boolean | null>(persisted?.isAuthenticated ?? null);
    user = $state<UserResponse | null>(persisted?.user ?? null);
    csrfToken = $state<string | null>(persisted?.csrfToken ?? null);

    #initialized = false;
    #initPromise: Promise<boolean> | null = null;

    restoreFrom(session: Session) {
        this.isAuthenticated = true;
        this.user = session.user;
        this.csrfToken = session.csrfToken;
    }

    clearAuth() {
        this.isAuthenticated = false;
        this.user = null;
        this.csrfToken = null;
        persistAuthState(null);
        // Nothing the previous user loaded may show to the next one
        queryClient.removeQueries();
    }

    async initialize(): Promise<boolean> {
        if (this.#initialized) return true;
        if (this.#initPromise) return this.#initPromise;

        this.#initPromise = this.#performInitialization();
        try {
            const result = await this.#initPromise;
            this.#initialized = true;
            return result;
        } catch (err) {
            log.error('Auth initialization failed:', err);
            this.#initialized = false;
            throw err;
        } finally {
            this.#initPromise = null;
        }
    }

    async waitForInit(): Promise<boolean> {
        if (this.#initialized) return true;
        if (this.#initPromise) return this.#initPromise;
        return this.initialize();
    }

    async #performInitialization(): Promise<boolean> {
        const persistedState = getPersistedAuthState();
        if (!persistedState) return this.verifyAuth();

        this.restoreFrom(persistedState);
        if (await this.verifyAuth(true)) return true;
        // A 401 has already cleared the session; after a network or server error a recent one stays
        if (this.isAuthenticated && Date.now() - persistedState.timestamp < STALE_AUTH_THRESHOLD) return true;
        this.clearAuth();
        return false;
    }

    /** Takes over the session a successful login started and loads the user's profile before it resolves. */
    async startSession(login: LoginResponse): Promise<void> {
        this.isAuthenticated = true;
        this.csrfToken = login.csrf_token;
        await this.verifyAuth(true);
    }

    /**
     * Checks the session with the server. The profile query is cached for 30 seconds, so checks within that
     * window share one answer, and checks made at the same time share one request.
     *
     * OFFLINE-FIRST: on a network or server error it returns the last answer instead of signing the user out,
     * so a server-revoked session can look valid for up to 30 seconds; pass forceRefresh for sensitive actions.
     */
    async verifyAuth(forceRefresh = false): Promise<boolean> {
        let user: UserResponse;
        try {
            user = await queryClient.query({
                ...getCurrentUserProfileApiV1AuthMeGetOptions(),
                staleTime: forceRefresh ? 0 : VERIFY_STALE_MS,
                retry: false,
            });
        } catch (err) {
            if (err instanceof ApiError && err.status === 401) {
                this.clearAuth();
                return false;
            }
            log.warn('Auth verification failed, keeping cached state:', err);
            return queryClient.getQueryData(getCurrentUserProfileApiV1AuthMeGetQueryKey()) !== undefined;
        }

        this.isAuthenticated = true;
        this.user = user;
        this.csrfToken = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/)?.[1] ?? null;
        persistAuthState({ isAuthenticated: true, user, csrfToken: this.csrfToken });
        return true;
    }
}

export const authStore = new AuthStore();
