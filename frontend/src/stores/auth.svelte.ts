import {
    loginApiV1AuthLoginPost,
    logoutApiV1AuthLogoutPost,
    verifyTokenApiV1AuthVerifyTokenGet,
    getCurrentUserProfileApiV1AuthMeGet,
} from '$lib/api';
import { clearUserSettings } from '$stores/userSettings.svelte';

export interface AuthState {
    isAuthenticated: boolean | null;
    username: string | null;
    userId: string | null;
    userRole: string | null;
    userEmail: string | null;
    csrfToken: string | null;
    timestamp: number;
}

export function getPersistedAuthState(): AuthState | null {
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
const STALE_AUTH_THRESHOLD = 5 * 60 * 1000;

class AuthStore {
    isAuthenticated = $state<boolean | null>(persisted?.isAuthenticated ?? null);
    username = $state<string | null>(persisted?.username ?? null);
    userId = $state<string | null>(persisted?.userId ?? null);
    userRole = $state<string | null>(persisted?.userRole ?? null);
    userEmail = $state<string | null>(persisted?.userEmail ?? null);
    csrfToken = $state<string | null>(persisted?.csrfToken ?? null);

    #authCache: { valid: boolean | null; timestamp: number } = { valid: null, timestamp: 0 };
    #verifyPromise: Promise<boolean> | null = null;
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
            console.error('Auth initialization failed:', err);
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

        if (persistedState) {
            this.restoreFrom(persistedState);
            const isValid = await this.verifyAuth(true);
            if (!isValid) {
                // Distinguish network error from explicit token invalidation.
                // verifyAuth sets #authCache.valid = false when server says invalid,
                // but leaves it null on network error (no cache to fall back to).
                if (this.#authCache.valid === null && Date.now() - persistedState.timestamp < STALE_AUTH_THRESHOLD) {
                    return true;
                }
                this.clearAuth();
                clearUserSettings();
                return false;
            }
            await this.#loadUserSettingsSafely();
            return true;
        }

        const isValid = await this.verifyAuth();
        if (isValid) await this.#loadUserSettingsSafely();
        return isValid;
    }

    async #loadUserSettingsSafely(): Promise<void> {
        try {
            // Dynamic import to avoid circular dependency:
            // auth.svelte.ts -> user-settings.ts -> auth.svelte.ts
            const { loadUserSettings } = await import('$lib/user-settings');
            await loadUserSettings();
        } catch (err) {
            console.warn('Failed to load user settings:', err);
        }
    }

    async login(user: string, password: string): Promise<boolean> {
        const { data, error } = await loginApiV1AuthLoginPost({
            body: { username: user, password, scope: '' }
        });
        if (error) throw error;

        this.isAuthenticated = true;
        this.username = data.username;
        this.userRole = data.role;
        this.csrfToken = data.csrf_token;
        this.userId = null;
        this.userEmail = null;

        persistAuthState({
            isAuthenticated: true,
            username: data.username,
            userRole: data.role,
            csrfToken: data.csrf_token,
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
        if (error) throw error;
        this.userId = data!.user_id;
        this.userEmail = data!.email;
        const current = getPersistedAuthState();
        if (current) persistAuthState({ ...current, userId: data!.user_id, userEmail: data!.email });
        return data;
    }

    async logout(): Promise<void> {
        try {
            await logoutApiV1AuthLogoutPost({});
        } catch (err) {
            console.error('Logout API call failed:', err);
        } finally {
            this.clearAuth();
            clearUserSettings();
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
                if (error || !data.valid) {
                    this.clearAuth();
                    this.#authCache = { valid: false, timestamp: Date.now() };
                    return false;
                }
                this.isAuthenticated = true;
                this.username = data.username;
                this.userRole = data.role;
                this.csrfToken = data.csrf_token;
                const current = getPersistedAuthState();
                persistAuthState({
                    isAuthenticated: true,
                    username: data.username,
                    userRole: data.role,
                    csrfToken: data.csrf_token,
                    userId: current?.userId ?? null,
                    userEmail: current?.userEmail ?? null
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
                this.clearAuth();
                return false;
            } finally {
                this.#verifyPromise = null;
            }
        })();
        return this.#verifyPromise;
    }
}

export const authStore = new AuthStore();
