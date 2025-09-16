import { writable, get } from 'svelte/store';

const browser = typeof window !== 'undefined' && typeof document !== 'undefined';
const CACHE_KEY = 'integr8scode-user-settings';
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

// Create a writable store for settings
export const settingsCache = writable(null);

// Cache structure: { data: settings, timestamp: Date.now() }
function getCachedSettings() {
    if (!browser) return null;
    
    try {
        const cached = localStorage.getItem(CACHE_KEY);
        if (!cached) return null;
        
        const { data, timestamp } = JSON.parse(cached);
        
        // Check if cache is expired
        if (Date.now() - timestamp > CACHE_TTL) {
            localStorage.removeItem(CACHE_KEY);
            return null;
        }
        
        return data;
    } catch (error) {
        console.error('Error reading settings cache:', error);
        localStorage.removeItem(CACHE_KEY);
        return null;
    }
}

function setCachedSettings(settings) {
    if (!browser) return;
    
    try {
        const cacheData = {
            data: settings,
            timestamp: Date.now()
        };
        localStorage.setItem(CACHE_KEY, JSON.stringify(cacheData));
        settingsCache.set(settings);
    } catch (error) {
        console.error('Error saving settings cache:', error);
    }
}

function clearCache() {
    if (!browser) return;
    
    localStorage.removeItem(CACHE_KEY);
    settingsCache.set(null);
}

// Update specific setting in cache
function updateCachedSetting(path, value) {
    const current = get(settingsCache);
    if (!current) return;
    
    const updated = { ...current };
    const pathParts = path.split('.');
    let target = updated;
    
    for (let i = 0; i < pathParts.length - 1; i++) {
        const part = pathParts[i];
        if (!target[part]) {
            target[part] = {};
        }
        target = target[part];
    }
    
    target[pathParts[pathParts.length - 1]] = value;
    setCachedSettings(updated);
}

// Load cached settings on initialization
if (browser) {
    const cached = getCachedSettings();
    if (cached) {
        settingsCache.set(cached);
    }
}

export {
    getCachedSettings,
    setCachedSettings,
    clearCache,
    updateCachedSetting
};