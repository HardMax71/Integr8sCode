import { navigate } from 'svelte-routing';
import { addNotification } from '../stores/notifications.js';
import { isAuthenticated, username, userId, userRole, csrfToken } from '../stores/auth.js';


export function handleSessionExpired() {
    // Save current path for redirect after login
    const currentPath = window.location.pathname + window.location.search + window.location.hash;
    if (currentPath !== '/login' && currentPath !== '/register') {
        sessionStorage.setItem('redirectAfterLogin', currentPath);
    }
    
    // Clear all auth state
    isAuthenticated.set(false);
    username.set(null);
    userId.set(null);
    userRole.set(null);
    csrfToken.set(null);
    
    // Show notification
    addNotification('Session expired. Please log in again.', 'warning');
    
    // Redirect to login
    navigate('/login');
}

/**
 * Check if a response indicates session expiration
 * @param {Response} response - The fetch response
 * @returns {boolean} - True if session expired
 */
export function isSessionExpired(response) {
    return response.status === 401;
}