import { authStore } from '$stores/auth.svelte';
import { clearUserSettings } from '$stores/userSettings.svelte';
import { loadUserSettings } from '$lib/user-settings';

interface PersistedAuth {
    isAuthenticated: boolean;
    username: string | null;
    userId: string | null;
    userRole: string | null;
    userEmail: string | null;
    csrfToken: string | null;
    timestamp: number;
}

export class AuthInitializer {
    static initialized = false;
    static initPromise: Promise<boolean> | null = null;

    static async initialize(): Promise<boolean> {
        if (this.initialized) {
            return true;
        }

        if (this.initPromise) {
            return this.initPromise;
        }

        this.initPromise = this._performInitialization();

        try {
            const result = await this.initPromise;
            this.initialized = true;
            return result;
        } catch (err) {
            console.error('Auth initialization failed:', err);
            this.initialized = false;
            throw err;
        } finally {
            this.initPromise = null;
        }
    }

    private static async _performInitialization(): Promise<boolean> {
        console.log('[AuthInit] Starting authentication initialization...');

        const persistedAuth = this._getPersistedAuth();

        if (persistedAuth) {
            return await this._handlePersistedAuth(persistedAuth);
        }

        return await this._handleNoPersistedAuth();
    }

    private static async _handlePersistedAuth(persistedAuth: PersistedAuth): Promise<boolean> {
        console.log('[AuthInit] Found persisted auth state, verifying with backend...');

        this._setAuthStores(persistedAuth);

        try {
            const isValid = await authStore.verifyAuth(true);

            if (!isValid) {
                console.log('[AuthInit] Authentication invalid, clearing state');
                this._clearAuth();
                return false;
            }

            console.log('[AuthInit] Authentication verified successfully');
            await this._loadUserSettingsSafely();
            return true;

        } catch (err) {
            console.error('[AuthInit] Verification failed:', err);
            return this._handleVerificationError(persistedAuth);
        }
    }

    private static async _handleNoPersistedAuth(): Promise<boolean> {
        console.log('[AuthInit] No persisted auth state found');

        try {
            const isValid = await authStore.verifyAuth();
            console.log('[AuthInit] Backend verification result:', isValid);

            if (isValid) {
                await this._loadUserSettingsSafely();
            }

            return isValid;
        } catch (err) {
            console.error('[AuthInit] Backend verification failed:', err);
            this._clearAuth();
            return false;
        }
    }

    private static _setAuthStores(authData: PersistedAuth): void {
        authStore.isAuthenticated = true;
        authStore.username = authData.username;
        authStore.userId = authData.userId;
        authStore.userRole = authData.userRole;
        authStore.userEmail = authData.userEmail;
        authStore.csrfToken = authData.csrfToken;
    }

    private static async _loadUserSettingsSafely(): Promise<void> {
        try {
            await loadUserSettings();
            console.log('[AuthInit] User settings loaded');
        } catch (err) {
            console.warn('[AuthInit] Failed to load user settings:', err);
        }
    }

    private static _handleVerificationError(persistedAuth: PersistedAuth): boolean {
        if (this._isRecentAuth(persistedAuth)) {
            console.log('[AuthInit] Network error but auth is recent, keeping state');
            return true;
        }

        console.log('[AuthInit] Network error and auth is stale, clearing state');
        this._clearAuth();
        return false;
    }

    private static _getPersistedAuth(): PersistedAuth | null {
        try {
            const authData = sessionStorage.getItem('authState');
            if (!authData) return null;
            return JSON.parse(authData);
        } catch (e) {
            console.error('[AuthInit] Failed to parse persisted auth:', e);
            return null;
        }
    }

    private static _isRecentAuth(authData: PersistedAuth): boolean {
        return Date.now() - authData.timestamp < 5 * 60 * 1000;
    }

    private static _clearAuth(): void {
        authStore.clearAuth();
        clearUserSettings();
    }

    static isAuthenticated(): boolean {
        if (!this.initialized) {
            console.warn('[AuthInit] Checking auth before initialization');
            return false;
        }
        return authStore.isAuthenticated ?? false;
    }

    static async waitForInit(): Promise<boolean> {
        if (this.initialized) return true;
        if (this.initPromise) return this.initPromise;
        return this.initialize();
    }
}

export const initializeAuth = (): Promise<boolean> => AuthInitializer.initialize();
export const waitForAuth = (): Promise<boolean> => AuthInitializer.waitForInit();
export const checkAuth = (): boolean => AuthInitializer.isAuthenticated();
