import { clearCache } from './settings-cache.js';

/**
 * Clear the settings cache (e.g., on logout)
 */
export function clearSettingsCache() {
    clearCache();
}