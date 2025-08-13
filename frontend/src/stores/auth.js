import { writable, get } from 'svelte/store';
import { backendUrl } from "../config.js";
import { fetchWithRetry } from "../lib/fetch-utils.js";
import { clearSettingsCache } from "../lib/auth-utils.js";

// Helper to get persisted auth state from localStorage
function getPersistedAuthState() {
    if (typeof window === 'undefined') return null;
    
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
        console.error('Failed to parse persisted auth state:', e);
        return null;
    }
}

// Initialize stores with persisted state or null (unknown state)
const persistedState = getPersistedAuthState();
export const isAuthenticated = writable(persistedState ? persistedState.isAuthenticated : null);
export const username = writable(persistedState ? persistedState.username : null);
export const userId = writable(persistedState ? persistedState.userId : null);
export const userRole = writable(persistedState ? persistedState.userRole : null);
export const userEmail = writable(persistedState ? persistedState.userEmail : null);
export const csrfToken = writable(persistedState ? persistedState.csrfToken : null);

// Helper to persist auth state to localStorage
function persistAuthState(authenticated, user, email, role, id, csrf) {
    if (typeof window === 'undefined') return;
    
    try {
        if (authenticated) {
            const authData = {
                isAuthenticated: authenticated,
                username: user,
                userId: id,
                userRole: role,
                userEmail: email,
                csrfToken: csrf,
                timestamp: Date.now()
            };
            localStorage.setItem('authState', JSON.stringify(authData));
        } else {
            localStorage.removeItem('authState');
        }
    } catch (e) {
        console.error('Failed to persist auth state:', e);
    }
}

// Cache for auth verification
let authCache = {
    valid: null,
    timestamp: 0
};
const AUTH_CACHE_DURATION = 30000; // 30 seconds

// Deduplication for concurrent requests
let verifyAuthPromise = null;

export async function login(usernameValue, password) {
    try {
        const formData = new URLSearchParams();
        formData.append('username', usernameValue);
        formData.append('password', password);

        const response = await fetchWithRetry(`/api/v1/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: formData
        }, {
            numOfAttempts: 3,
            maxDelay: 5000
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Login failed');
        }

        const data = await response.json();
        // Token is now stored in httpOnly cookie, just update auth state
        isAuthenticated.set(true);
        username.set(data.username || usernameValue);
        userId.set(data.user_id);
        userRole.set(data.role || 'user');
        userEmail.set(data.email || null);
        csrfToken.set(data.csrf_token);
        
        // Persist auth state to localStorage
        persistAuthState(
            true,
            data.username || usernameValue,
            data.email || null,
            data.role || 'user',
            data.user_id,
            data.csrf_token
        );
        
        // Invalidate cache on login
        authCache = {
            valid: true,
            timestamp: Date.now()
        };
        
        return true;
    } catch (error) {
        console.error("Login failed:", error);
        throw error;
    }
}

export async function logout() {
    try {
        const response = await fetchWithRetry('/api/v1/auth/logout', {
            method: 'POST'
        }, {
            numOfAttempts: 2,
            maxDelay: 3000
        });

        // Clear auth state regardless of response (cookie might be expired)
        isAuthenticated.set(false);
        username.set(null);
        userId.set(null);
        userRole.set(null);
        userEmail.set(null);
        csrfToken.set(null);
        
        // Clear persisted auth state
        persistAuthState(false);
        
        // Clear settings cache
        clearSettingsCache();
        
        // Invalidate cache on logout
        authCache = {
            valid: false,
            timestamp: Date.now()
        };

        if (!response.ok) {
            console.warn('Logout request failed, but cleared local auth state');
        }
    } catch (error) {
        console.error('Logout error:', error);
        isAuthenticated.set(false);
        username.set(null);
        userId.set(null);
        userRole.set(null);
        userEmail.set(null);
        csrfToken.set(null);
        
        // Clear persisted auth state
        persistAuthState(false);
        
        // Clear settings cache
        clearSettingsCache();
    }
}

export async function verifyAuth(forceRefresh = false) {
    // Return cached result if still valid
    if (!forceRefresh && authCache.valid !== null && Date.now() - authCache.timestamp < AUTH_CACHE_DURATION) {
        return authCache.valid;
    }
    
    // If there's already a verification in progress, return the same promise
    if (verifyAuthPromise) {
        return verifyAuthPromise;
    }
    
    // Create new verification promise
    verifyAuthPromise = (async () => {
        try {
            const response = await fetchWithRetry('/api/v1/auth/verify-token', {
                method: 'GET'
            }, {
                numOfAttempts: 2, // Reduced from 3
                maxDelay: 2000 // Reduced from 5000ms
            });

            if (response.ok) {
                const data = await response.json();
                isAuthenticated.set(data.valid);
                username.set(data.username);
                userId.set(data.user_id);
                userRole.set(data.role || 'user');
                userEmail.set(data.email || null);
                csrfToken.set(data.csrf_token);
                
                // Persist auth state if valid
                if (data.valid) {
                    persistAuthState(
                        true,
                        data.username,
                        data.email || null,
                        data.role || 'user',
                        data.user_id,
                        data.csrf_token
                    );
                }
                
                // Update cache
                authCache = {
                    valid: data.valid,
                    timestamp: Date.now()
                };
                
                return data.valid;
            } else if (response.status === 401) {
                // Not authenticated - this is expected for non-logged-in users
                isAuthenticated.set(false);
                username.set(null);
                userId.set(null);
                userRole.set(null);
                userEmail.set(null);
                csrfToken.set(null);
                
                // Clear persisted auth state
                persistAuthState(false);
                
                // Update cache
                authCache = {
                    valid: false,
                    timestamp: Date.now()
                };
                
                return false;
            } else {
                // Other error - don't cache this
                console.error('Token verification error:', response.status);
                isAuthenticated.set(false);
                username.set(null);
                userId.set(null);
                userRole.set(null);
                userEmail.set(null);
                csrfToken.set(null);
                return false;
            }
        } catch (error) {
            // Network error or other issue - don't cache this
            console.error('Auth verification failed:', error);
            
            // If we have a cached value and network failed, use cached value
            if (authCache.valid !== null) {
                console.log('Using cached auth state due to network error');
                return authCache.valid;
            }
            
            isAuthenticated.set(false);
            username.set(null);
            userId.set(null);
            userRole.set(null);
            userEmail.set(null);
            csrfToken.set(null);
            return false;
        } finally {
            // Clear the promise so future calls create a new one
            verifyAuthPromise = null;
        }
    })();
    
    return verifyAuthPromise;
}