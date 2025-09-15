import { get } from 'svelte/store';
import { isAuthenticated, username, userId, userRole, userEmail, csrfToken, verifyAuth } from '../stores/auth.js';
import { loadUserSettings } from './user-settings.js';

/**
 * Authentication initialization service
 * This runs before any components mount to ensure auth state is ready
 */
export class AuthInitializer {
    static initialized = false;
    static initPromise = null;

    /**
     * Initialize authentication state from localStorage and verify with backend
     * This should be called once at app startup
     */
    static async initialize() {
        // If already initialized or initializing, return the existing promise
        if (this.initialized) {
            return true;
        }
        
        if (this.initPromise) {
            return this.initPromise;
        }

        // Create initialization promise
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

    static async _performInitialization() {
        console.log('[AuthInit] Starting authentication initialization...');

        // Check if we have persisted auth state
        const persistedAuth = this._getPersistedAuth();

        if (persistedAuth) {
            return await this._handlePersistedAuth(persistedAuth);
        }

        return await this._handleNoPersistedAuth();
    }

    static async _handlePersistedAuth(persistedAuth) {
        console.log('[AuthInit] Found persisted auth state, verifying with backend...');

        // Set stores immediately to avoid UI flicker
        this._setAuthStores(persistedAuth);

        try {
            const isValid = await verifyAuth(true); // Force refresh

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

    static async _handleNoPersistedAuth() {
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

    static _setAuthStores(authData) {
        isAuthenticated.set(true);
        username.set(authData.username);
        userId.set(authData.userId);
        userRole.set(authData.userRole);
        userEmail.set(authData.userEmail);
        csrfToken.set(authData.csrfToken);
    }

    static async _loadUserSettingsSafely() {
        try {
            await loadUserSettings();
            console.log('[AuthInit] User settings loaded');
        } catch (error) {
            console.warn('[AuthInit] Failed to load user settings:', error);
            // Continue even if settings fail to load
        }
    }

    static _handleVerificationError(persistedAuth) {
        // On network error, keep the persisted state if it's recent
        if (this._isRecentAuth(persistedAuth)) {
            console.log('[AuthInit] Network error but auth is recent, keeping state');
            return true;
        }

        console.log('[AuthInit] Network error and auth is stale, clearing state');
        this._clearAuth();
        return false;
    }

    static _getPersistedAuth() {
        try {
            const authData = localStorage.getItem('authState');
            if (!authData) return null;
            
            const parsed = JSON.parse(authData);
            
            // Check if auth data is still fresh (24 hours)
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

    static _isRecentAuth(authData) {
        // Consider auth recent if less than 5 minutes old
        return authData && (Date.now() - authData.timestamp < 5 * 60 * 1000);
    }

    static _clearAuth() {
        isAuthenticated.set(false);
        username.set(null);
        userId.set(null);
        userRole.set(null);
        userEmail.set(null);
        csrfToken.set(null);
        localStorage.removeItem('authState');
    }

    /**
     * Check if user is authenticated (after initialization)
     */
    static isAuthenticated() {
        if (!this.initialized) {
            console.warn('[AuthInit] Checking auth before initialization');
            return false;
        }
        return get(isAuthenticated);
    }

    /**
     * Wait for initialization to complete
     */
    static async waitForInit() {
        if (this.initialized) return true;
        if (this.initPromise) return this.initPromise;
        return this.initialize();
    }
}

// Export singleton instance methods for convenience
export const initializeAuth = () => AuthInitializer.initialize();
export const waitForAuth = () => AuthInitializer.waitForInit();
export const checkAuth = () => AuthInitializer.isAuthenticated();