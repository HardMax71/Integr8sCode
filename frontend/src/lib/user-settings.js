import { setTheme } from '../stores/theme.js';
import { get } from 'svelte/store';
import { isAuthenticated } from '../stores/auth.js';
import { getCachedSettings, setCachedSettings, updateCachedSetting } from './settings-cache.js';


export async function saveThemeSetting(theme) {
    // Only save if user is authenticated
    if (!get(isAuthenticated)) {
        return;
    }
    
    try {
        const response = await fetch('/api/v1/user/settings/theme', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ theme })
        });
        
        if (!response.ok) {
            console.error('Failed to save theme setting');
            throw new Error('Failed to save theme');
        }
        
        // Update cache
        updateCachedSetting('theme', theme);
        
        console.log('Theme setting saved:', theme);
        return true;
    } catch (error) {
        console.error('Error saving theme setting:', error);
        // Don't show notification for theme save failure - it's not critical
        return false;
    }
}

/**
 * Load user settings from the backend and apply them
 */
export async function loadUserSettings() {
    // First check cache
    const cached = getCachedSettings();
    if (cached) {
        // Apply cached settings immediately
        if (cached.theme) {
            setTheme(cached.theme);
        }
        return cached;
    }
    
    try {
        const response = await fetch('/api/v1/user/settings/', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include'
        });
        
        if (!response.ok) {
            // If settings don't exist or error, just use defaults
            console.warn('Could not load user settings, using defaults');
            return;
        }
        
        const settings = await response.json();
        
        // Cache the settings
        setCachedSettings(settings);
        
        // Apply theme if it exists
        if (settings.theme) {
            setTheme(settings.theme);
        }
        
        // Could apply other settings here in the future
        
        return settings;
    } catch (error) {
        console.error('Failed to load user settings:', error);
        // Don't show notification for settings load failure - just use defaults
    }
}

/**
 * Save editor settings to backend
 */
export async function saveEditorSettings(editorSettings) {
    // Only save if user is authenticated
    if (!get(isAuthenticated)) {
        return;
    }
    
    try {
        const response = await fetch('/api/v1/user/settings/', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ editor: editorSettings })
        });
        
        if (!response.ok) {
            console.error('Failed to save editor settings');
            throw new Error('Failed to save editor settings');
        }
        
        // Update cache
        updateCachedSetting('editor', editorSettings);
        
        console.log('Editor settings saved');
        return true;
    } catch (error) {
        console.error('Error saving editor settings:', error);
        return false;
    }
}