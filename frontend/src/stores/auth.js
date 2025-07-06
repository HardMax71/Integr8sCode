import { writable } from 'svelte/store';
import {backendUrl} from "../config.js";
import {fetchWithRetry} from "../lib/api.js";

export const isAuthenticated = writable(false);
export const username = writable(null);
export const csrfToken = writable(null);

export async function login(email, password) {
    try {
        const formData = new URLSearchParams();
        formData.append('username', email);
        formData.append('password', password);

        const response = await fetchWithRetry(`/api/v1/login`, {
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
        username.set(data.username || email);
        csrfToken.set(data.csrf_token);
        return true;
    } catch (error) {
        console.error("Login failed:", error);
        throw error;
    }
}

export async function logout() {
    try {
        const response = await fetchWithRetry('/api/v1/logout', {
            method: 'POST'
        }, {
            numOfAttempts: 2,
            maxDelay: 3000
        });

        // Clear auth state regardless of response (cookie might be expired)
        isAuthenticated.set(false);
        username.set(null);
        csrfToken.set(null);

        if (!response.ok) {
            console.warn('Logout request failed, but cleared local auth state');
        }
    } catch (error) {
        console.error('Logout error:', error);
        isAuthenticated.set(false);
        username.set(null);
        csrfToken.set(null);
    }
}

export async function verifyAuth() {
    try {
        const response = await fetchWithRetry('/api/v1/verify-token', {
            method: 'GET'
        }, {
            numOfAttempts: 3,
            maxDelay: 5000
        });

        if (response.ok) {
            const data = await response.json();
            isAuthenticated.set(data.valid);
            username.set(data.username);
            csrfToken.set(data.csrf_token);
            return data.valid;
        } else {
            isAuthenticated.set(false);
            username.set(null);
            csrfToken.set(null);
            return false;
        }
    } catch (error) {
        console.error('Auth verification failed:', error);
        isAuthenticated.set(false);
        username.set(null);
        csrfToken.set(null);
        return false;
    }
}