import { get } from 'svelte/store';
import { isAuthenticated, username, userId, userRole, userEmail, csrfToken, verifyAuth } from '../stores/auth';
import { loadUserSettings } from './user-settings';

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
        } catch (error) {
            console.error('Auth initialization failed:', error);
            this.initialized = false;
            throw error;
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
            const isValid = await verifyAuth(true);

            if (!isValid) {
                console.log('[AuthInit] Authentication invalid, clearing state');
                this._clearAuth();
                return false;
            }

            console.log('[AuthInit] Authentication verified successfully');
            await this._loadUserSettingsSafely();
            return true;

        } catch (error) {
            console.error('[AuthInit] Verification failed:', error);
            return this._handleVerificationError(persistedAuth);
        }
    }

    private static async _handleNoPersistedAuth(): Promise<boolean> {
        console.log('[AuthInit] No persisted auth state found');

        try {
            const isValid = await verifyAuth();
            console.log('[AuthInit] Backend verification result:', isValid);

            if (isValid) {
                await this._loadUserSettingsSafely();
            }

            return isValid;
        } catch (error) {
            console.error('[AuthInit] Backend verification failed:', error);
            this._clearAuth();
            return false;
        }
    }

    private static _setAuthStores(authData: PersistedAuth): void {
        isAuthenticated.set(true);
        username.set(authData.username);
        userId.set(authData.userId);
        userRole.set(authData.userRole);
        userEmail.set(authData.userEmail);
        csrfToken.set(authData.csrfToken);
    }

    private static async _loadUserSettingsSafely(): Promise<void> {
        try {
            await loadUserSettings();
            console.log('[AuthInit] User settings loaded');
        } catch (error) {
            console.warn('[AuthInit] Failed to load user settings:', error);
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
            const authData = localStorage.getItem('authState');
            if (!authData) return null;

            const parsed: PersistedAuth = JSON.parse(authData);

            if (Date.now() - parsed.timestamp > 24 * 60 * 60 * 1000) {
                localStorage.removeItem('authState');
                return null;
            }

            return parsed;
        } catch (e) {
            console.error('[AuthInit] Failed to parse persisted auth:', e);
            return null;
        }
    }

    private static _isRecentAuth(authData: PersistedAuth): boolean {
        return Date.now() - authData.timestamp < 5 * 60 * 1000;
    }

    private static _clearAuth(): void {
        isAuthenticated.set(false);
        username.set(null);
        userId.set(null);
        userRole.set(null);
        userEmail.set(null);
        csrfToken.set(null);
        localStorage.removeItem('authState');
    }

    static isAuthenticated(): boolean {
        if (!this.initialized) {
            console.warn('[AuthInit] Checking auth before initialization');
            return false;
        }
        return get(isAuthenticated) ?? false;
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
