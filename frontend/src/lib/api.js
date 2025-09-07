import { get } from 'svelte/store';
import { csrfToken } from '../stores/auth.js';
import { fetchWithRetry } from './fetch-utils.js';
import { handleSessionExpired, isSessionExpired } from './session-handler.js';
import { requestManager } from './request-manager.js';

// Re-export fetchWithRetry for backward compatibility
export { fetchWithRetry };

/**
 * Make an authenticated request with CSRF token and retry logic
 * @param {string} url - The URL to request
 * @param {Object} options - Request options
 * @param {Object} retryOptions - Retry configuration
 * @returns {Promise<Response>} - The response
 */
export async function makeAuthenticatedRequest(url, options = {}, retryOptions = {}) {
    return fetchWithRetry(url, {
        ...options,
        headers: {
            ...options.headers,
            ...addCSRFTokenToHeaders(options.method)
        }
    }, retryOptions);
}

/**
 * Add CSRF token to headers if needed
 * @param {string} method - HTTP method
 * @returns {Object} - Headers object with CSRF token if applicable
 */
function addCSRFTokenToHeaders(method) {
    const headers = {};
    
    // Add CSRF token for state-changing requests
    if (method && !['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())) {
        const token = get(csrfToken);
        if (token) {
            headers['X-CSRF-Token'] = token;
        }
    }
    
    return headers;
}

/**
 * Generic API call helper with retry logic
 * @param {string} url - The URL to request
 * @param {Object} options - Request options
 * @param {Object} retryOptions - Retry configuration
 * @returns {Promise<any>} - Parsed JSON response
 */
export async function apiCall(url, options = {}, retryOptions = {}) {
    const response = await makeAuthenticatedRequest(url, options, retryOptions);
    
    // Handle session expiration
    if (isSessionExpired(response)) {
        handleSessionExpired();
        
        // Throw error to stop further processing
        const error = new Error('Session expired');
        error.response = response;
        throw error;
    }
    
    if (!response.ok) {
        const error = new Error(`HTTP ${response.status}: ${response.statusText}`);
        error.response = response;
        throw error;
    }
    
    // Only parse JSON if response has content
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
        return response.json();
    }
    
    return response;
}

// Export an api object for convenience
export const api = {
    get: (url, options = {}) => {
        // Use request manager for GET requests to prevent duplicates
        return requestManager.dedupedRequest(url, 
            () => apiCall(url, { ...options, method: 'GET' }),
            { method: 'GET', ...options }
        );
    },
    post: (url, data, options = {}) => apiCall(url, { 
        ...options, 
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        },
        body: JSON.stringify(data)
    }),
    put: (url, data, options = {}) => apiCall(url, {
        ...options,
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        },
        body: JSON.stringify(data)
    }),
    delete: (url, options = {}) => apiCall(url, { ...options, method: 'DELETE' }),
    clearCache: (pattern) => requestManager.clearCache(pattern)
};