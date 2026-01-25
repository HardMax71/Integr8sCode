import { writable } from 'svelte/store';
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
export const isAuthenticated = writable<boolean | null>(persisted?.isAuthenticated ?? null);
export const username = writable<string | null>(persisted?.username ?? null);
export const userId = writable<string | null>(persisted?.userId ?? null);
export const userRole = writable<string | null>(persisted?.userRole ?? null);
export const userEmail = writable<string | null>(persisted?.userEmail ?? null);
export const csrfToken = writable<string | null>(persisted?.csrfToken ?? null);

let authCache: { valid: boolean | null; timestamp: number } = { valid: null, timestamp: 0 };
const AUTH_CACHE_DURATION = 30000;
let verifyPromise: Promise<boolean> | null = null;

function clearAuth() {
    isAuthenticated.set(false);
    username.set(null);
    userId.set(null);
    userRole.set(null);
    userEmail.set(null);
    csrfToken.set(null);
    persistAuthState(null);
}

export async function login(user: string, password: string): Promise<boolean> {
    const { data, error } = await loginApiV1AuthLoginPost({
        body: { username: user, password, scope: '' }
    });
    if (error || !data) throw error ?? new Error('Login failed');

    isAuthenticated.set(true);
    username.set(data.username ?? user);
    userRole.set(data.role ?? 'user');
    csrfToken.set(data.csrf_token ?? null);
    userId.set(null);
    userEmail.set(null);

    persistAuthState({
        isAuthenticated: true,
        username: data.username ?? user,
        userRole: data.role ?? 'user',
        csrfToken: data.csrf_token ?? null,
        userId: null,
        userEmail: null
    });

    authCache = { valid: true, timestamp: Date.now() };
    try {
        await fetchUserProfile();
    } catch (err) {
        console.warn('Failed to fetch user profile after login:', err);
    }
    return true;
}

export async function fetchUserProfile() {
    const { data, error } = await getCurrentUserProfileApiV1AuthMeGet({});
    if (error || !data) throw error ?? new Error('Failed to fetch profile');
    userId.set(data.user_id);
    userEmail.set(data.email ?? null);
    const current = getPersistedAuthState();
    if (current) persistAuthState({ ...current, userId: data.user_id, userEmail: data.email ?? null });
    return data;
}

export async function logout(): Promise<void> {
    try {
        await logoutApiV1AuthLogoutPost({});
    } catch (err) {
        console.error('Logout API call failed:', err);
    } finally {
        clearAuth();
        authCache = { valid: false, timestamp: Date.now() };
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
export async function verifyAuth(forceRefresh = false): Promise<boolean> {
    if (!forceRefresh && authCache.valid !== null && Date.now() - authCache.timestamp < AUTH_CACHE_DURATION) {
        return authCache.valid;
    }
    if (verifyPromise) return verifyPromise;

    verifyPromise = (async () => {
        try {
            const { data, error } = await verifyTokenApiV1AuthVerifyTokenGet({});
            if (error || !data?.valid) {
                clearAuth();
                authCache = { valid: false, timestamp: Date.now() };
                return false;
            }
            isAuthenticated.set(true);
            username.set(data.username ?? null);
            userRole.set(data.role ?? 'user');
            csrfToken.set(data.csrf_token ?? null);
            persistAuthState({
                isAuthenticated: true,
                username: data.username ?? null,
                userRole: data.role ?? 'user',
                csrfToken: data.csrf_token ?? null,
                userId: null,
                userEmail: null
            });
            authCache = { valid: true, timestamp: Date.now() };
            try {
                await fetchUserProfile();
            } catch (err) {
                console.warn('Failed to fetch user profile during verification:', err);
            }
            return true;
        } catch (err) {
            // Network error - use cached state if available (offline-first)
            // See function docstring for security trade-off explanation
            console.warn('Auth verification failed (network error):', err);
            if (authCache.valid !== null) return authCache.valid;
            clearAuth();
            return false;
        } finally {
            verifyPromise = null;
        }
    })();
    return verifyPromise;
}
