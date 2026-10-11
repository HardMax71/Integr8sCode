import {
    getCurrentUserProfileApiV1AuthMeGetOptions,
    getCurrentUserProfileApiV1AuthMeGetQueryKey,
    type LoginResponse,
    type UserResponse,
    type UserRole,
} from '#lib/api/index.ts';
import { ApiError } from '#lib/api-error.ts';
import { queryClient } from '#lib/query-client.ts';
import { logger } from '#lib/logger.ts';

const log = logger.withTag('Auth');

// --8<-- [start:AuthState]
export interface AuthState {
    isAuthenticated: boolean | null;
    username: string | null;
    userId: string | null;
    userRole: UserRole | null;
    userEmail: string | null;
    csrfToken: string | null;
    timestamp: number;
}
// --8<-- [end:AuthState]

export function getPersistedAuthState(): AuthState | null {
    if (typeof window === 'undefined') return null;
    try {
        const data = sessionStorage.getItem('authState');
        if (!data) return null;
        return JSON.parse(data) as AuthState;
    } catch {
        return null;
    }
}

function persistAuthState(state: Partial<AuthState> | null) {
    if (typeof window === 'undefined') return;
    if (!state || state.isAuthenticated === false) {
        sessionStorage.removeItem('authState');
        return;
    }
    sessionStorage.setItem('authState', JSON.stringify({ ...state, timestamp: Date.now() }));
}

const persisted = getPersistedAuthState();

const VERIFY_STALE_MS = 30_000;
const STALE_AUTH_THRESHOLD = 5 * 60 * 1000;

class AuthStore {
    isAuthenticated = $state<boolean | null>(persisted?.isAuthenticated ?? null);
    username = $state<string | null>(persisted?.username ?? null);
    userId = $state<string | null>(persisted?.userId ?? null);
    userRole = $state<UserRole | null>(persisted?.userRole ?? null);
    userEmail = $state<string | null>(persisted?.userEmail ?? null);
    csrfToken = $state<string | null>(persisted?.csrfToken ?? null);

    #initialized = false;
    #initPromise: Promise<boolean> | null = null;

    restoreFrom(state: AuthState) {
        this.isAuthenticated = true;
        this.username = state.username;
        this.userId = state.userId;
        this.userRole = state.userRole;
        this.userEmail = state.userEmail;
        this.csrfToken = state.csrfToken;
    }

    clearAuth() {
        this.isAuthenticated = false;
        this.username = null;
        this.userId = null;
        this.userRole = null;
        this.userEmail = null;
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

    /** Takes over the session a successful login started, then loads the full profile. */
    async startSession(login: LoginResponse): Promise<void> {
        this.isAuthenticated = true;
        this.username = login.username;
        this.userRole = login.role;
        this.csrfToken = login.csrf_token;
        this.userId = null;
        this.userEmail = null;
        persistAuthState({
            isAuthenticated: true,
            username: login.username,
            userRole: login.role,
            csrfToken: login.csrf_token,
            userId: null,
            userEmail: null,
        });
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
        this.username = user.username;
        this.userRole = user.role;
        this.userId = user.user_id;
        this.userEmail = user.email;
        this.csrfToken = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/)?.[1] ?? null;
        persistAuthState({
            isAuthenticated: true,
            username: user.username,
            userRole: user.role,
            csrfToken: this.csrfToken,
            userId: user.user_id,
            userEmail: user.email,
        });
        return true;
    }
}

export const authStore = new AuthStore();
