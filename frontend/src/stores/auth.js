import { writable } from 'svelte/store';

function createPersistentStore(key, startValue) {
    const storedValue = localStorage.getItem(key);
    const store = writable(storedValue ? JSON.parse(storedValue) : startValue);

    store.subscribe(value => {
        localStorage.setItem(key, JSON.stringify(value));
    });

    return store;
}

export const authToken = createPersistentStore("auth_token", null);
export const username = createPersistentStore("username", null);

export async function login(email, password) {
    try {
        const formData = new URLSearchParams();
        formData.append('username', email);
        formData.append('password', password);

        const response = await fetch("http://localhost:8000/api/v1/login", {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: formData
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Login failed');
        }

        const data = await response.json();
        authToken.set(data.access_token);
        username.set(email);
        return true;
    } catch (error) {
        console.error("Login failed:", error);
        throw error;
    }
}

export function logout() {
    authToken.set(null);
    username.set(null);
}