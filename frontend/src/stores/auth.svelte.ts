import {
    loginApiV1AuthLoginPost,
    logoutApiV1AuthLogoutPost,
    verifyTokenApiV1AuthVerifyTokenGet,
    getCurrentUserProfileApiV1AuthMeGet,
} from '$lib/api';

interface AuthState {
    isAuthenticated: boolean | null;
    username: string | null;
    userId: string | null;
    userRole: string | null;
    userEmail: string | null;
    csrfToken: string | null;
    timestamp: number;
}

function getPersistedAuthState(): AuthState | null {
    if (typeof window === 'undefined') return null;
    try {
        const data = sessionStorage.getItem('authState');
        if (!data) return null;
        return JSON.parse(data) as AuthState;
    } catch { return null; }
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

const AUTH_CACHE_DURATION = 30000;

class AuthStore {
    isAuthenticated = $state<boolean | null>(persisted?.isAuthenticated ?? null);
    username = $state<string | null>(persisted?.username ?? null);
    userId = $state<string | null>(persisted?.userId ?? null);
    userRole = $state<string | null>(persisted?.userRole ?? null);
    userEmail = $state<string | null>(persisted?.userEmail ?? null);
    csrfToken = $state<string | null>(persisted?.csrfToken ?? null);

    #authCache: { valid: boolean | null; timestamp: number } = { valid: null, timestamp: 0 };
    #verifyPromise: Promise<boolean> | null = null;

    #clearAuth() {
        this.isAuthenticated = false;
        this.username = null;
        this.userId = null;
        this.userRole = null;
        this.userEmail = null;
        this.csrfToken = null;
        persistAuthState(null);
    }

    async login(user: string, password: string): Promise<boolean> {
        const { data, error } = await loginApiV1AuthLoginPost({
            body: { username: user, password, scope: '' }
        });
        if (error || !data) throw error ?? new Error('Login failed');

        this.isAuthenticated = true;
        this.username = data.username ?? user;
        this.userRole = data.role ?? 'user';
        this.csrfToken = data.csrf_token ?? null;
        this.userId = null;
        this.userEmail = null;

        persistAuthState({
            isAuthenticated: true,
            username: data.username ?? user,
            userRole: data.role ?? 'user',
            csrfToken: data.csrf_token ?? null,
            userId: null,
            userEmail: null
        });

        this.#authCache = { valid: true, timestamp: Date.now() };
        try {
            await this.fetchUserProfile();
        } catch (err) {
            console.warn('Failed to fetch user profile after login:', err);
        }
        return true;
    }

    async fetchUserProfile() {
        const { data, error } = await getCurrentUserProfileApiV1AuthMeGet({});
        if (error || !data) throw error ?? new Error('Failed to fetch profile');
        this.userId = data.user_id;
        this.userEmail = data.email ?? null;
        const current = getPersistedAuthState();
        if (current) persistAuthState({ ...current, userId: data.user_id, userEmail: data.email ?? null });
        return data;
    }

    async logout(): Promise<void> {
        try {
            await logoutApiV1AuthLogoutPost({});
        } catch (err) {
            console.error('Logout API call failed:', err);
        } finally {
            this.#clearAuth();
            this.#authCache = { valid: false, timestamp: Date.now() };
        }
    }

    /**
     * Verifies the current authentication state with the server.
     *
     * OFFLINE-FIRST BEHAVIOR: On network failure, this function returns the cached
     * auth state (if available) rather than immediately logging the user out.
     * This provides better UX during transient network issues but means:
     * - Server-revoked tokens may remain "valid" locally for up to AUTH_CACHE_DURATION (30s)
     * - Security-critical operations should use forceRefresh=true
     *
     * Trade-off: We prioritize availability over immediate consistency for better
     * offline/flaky-network UX. The 30-second cache window is acceptable for most
     * UI operations; sensitive actions should force re-verification.
     */
    async verifyAuth(forceRefresh = false): Promise<boolean> {
        if (!forceRefresh && this.#authCache.valid !== null && Date.now() - this.#authCache.timestamp < AUTH_CACHE_DURATION) {
            return this.#authCache.valid;
        }
        if (this.#verifyPromise) return this.#verifyPromise;

        this.#verifyPromise = (async () => {
            try {
                const { data, error } = await verifyTokenApiV1AuthVerifyTokenGet({});
                if (error || !data?.valid) {
                    this.#clearAuth();
                    this.#authCache = { valid: false, timestamp: Date.now() };
                    return false;
                }
                this.isAuthenticated = true;
                this.username = data.username ?? null;
                this.userRole = data.role ?? 'user';
                this.csrfToken = data.csrf_token ?? null;
                persistAuthState({
                    isAuthenticated: true,
                    username: data.username ?? null,
                    userRole: data.role ?? 'user',
                    csrfToken: data.csrf_token ?? null,
                    userId: null,
                    userEmail: null
                });
                this.#authCache = { valid: true, timestamp: Date.now() };
                try {
                    await this.fetchUserProfile();
                } catch (err) {
                    console.warn('Failed to fetch user profile during verification:', err);
                }
                return true;
            } catch (err) {
                // Network error - use cached state if available (offline-first)
                // See function docstring for security trade-off explanation
                console.warn('Auth verification failed (network error):', err);
                if (this.#authCache.valid !== null) return this.#authCache.valid;
                this.#clearAuth();
                return false;
            } finally {
                this.#verifyPromise = null;
            }
        })();
        return this.#verifyPromise;
    }
}

export const authStore = new AuthStore();
