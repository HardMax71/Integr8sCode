import { backOff } from 'exponential-backoff';

/**
 * Check if an error should trigger a retry
 */
export function shouldRetry(error) {
    // Check if error exists
    if (!error) {
        return false;
    }
    
    // Network errors
    if (error.name === 'TypeError' && error.message && error.message.includes('fetch')) {
        return true;
    }
    
    // Timeout errors should not retry
    if (error.name === 'TimeoutError' || error.name === 'AbortError') {
        return false;
    }
    
    // If it's a Response object, check status codes
    if (error instanceof Response) {
        const status = error.status;
        return status >= 500 || status === 408 || status === 429;
    }
    
    return false;
}

/**
 * Base fetch with retry logic using exponential-backoff
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
        timeout = 30000, // Add 30 second timeout
        ...otherRetryOptions
    } = retryOptions;

    return backOff(
        async () => {
            // Create an AbortController for timeout
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), timeout);
            
            try {
                const response = await fetch(url, {
                    credentials: 'include',
                    signal: controller.signal,
                    ...options
                });
                clearTimeout(timeoutId);
                
                // For retryable errors, throw to trigger retry logic
                if (!response.ok && shouldRetry(response)) {
                    const error = new Error(`HTTP ${response.status}: ${response.statusText}`);
                    error.response = response;
                    throw error;
                }
                
                return response;
            } catch (error) {
                clearTimeout(timeoutId);
                
                // If it's an abort error, wrap it with a more descriptive message
                if (error.name === 'AbortError') {
                    const timeoutError = new Error(`Request timeout after ${timeout}ms: ${url}`);
                    timeoutError.name = 'TimeoutError';
                    throw timeoutError;
                }
                
                throw error;
            }
        },
        {
            numOfAttempts,
            maxDelay,
            jitter,
            retry: (error) => shouldRetry(error) || (error && error.response && shouldRetry(error.response)),
            ...otherRetryOptions
        }
    );
}