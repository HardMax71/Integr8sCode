import { backOff } from 'exponential-backoff';
import { get } from 'svelte/store';
import { csrfToken } from '../stores/auth.js';

/**
 * Check if an error should trigger a retry
 */
function shouldRetry(error) {
    // Network errors
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
        return true;
    }
    
    // If it's a Response object, check status codes
    if (error instanceof Response) {
        const status = error.status;
        return status >= 500 || status === 408 || status === 429;
    }
    
    return false;
}

/**
 * Fetch with retry logic using exponential-backoff
 * @param {string} url - The URL to fetch
 * @param {Object} options - Fetch options
 * @param {Object} retryOptions - Retry configuration
 * @returns {Promise<Response>} - The fetch response
 */
export async function fetchWithRetry(url, options = {}, retryOptions = {}) {
    const {
        numOfAttempts = 3,
        maxDelay = 10000,
        jitter = 'none',
        ...otherRetryOptions
    } = retryOptions;

    return backOff(
        async () => {
            const response = await fetch(url, {
                credentials: 'include',
                ...options
            });
            
            // For retryable errors, throw to trigger retry logic
            if (!response.ok && shouldRetry(response)) {
                const error = new Error(`HTTP ${response.status}: ${response.statusText}`);
                error.response = response;
                throw error;
            }
            
            return response;
        },
        {
            numOfAttempts,
            maxDelay,
            jitter,
            retry: (error) => shouldRetry(error) || shouldRetry(error.response),
            ...otherRetryOptions
        }
    );
}

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