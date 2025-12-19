import { writable, get } from 'svelte/store';
import type { UserSettings } from './api';

const browser = typeof window !== 'undefined' && typeof document !== 'undefined';
const CACHE_KEY = 'integr8scode-user-settings';
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

interface CacheData {
    data: UserSettings;
    timestamp: number;
}

export const settingsCache = writable<UserSettings | null>(null);

export function getCachedSettings(): UserSettings | null {
    if (!browser) return null;

    try {
        const cached = localStorage.getItem(CACHE_KEY);
        if (!cached) return null;

        const { data, timestamp }: CacheData = JSON.parse(cached);

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

export function setCachedSettings(settings: UserSettings): void {
    if (!browser) return;

    try {
        const cacheData: CacheData = {
            data: settings,
            timestamp: Date.now()
        };
        localStorage.setItem(CACHE_KEY, JSON.stringify(cacheData));
        settingsCache.set(settings);
    } catch (error) {
        console.error('Error saving settings cache:', error);
    }
}

export function clearCache(): void {
    if (!browser) return;
    localStorage.removeItem(CACHE_KEY);
    settingsCache.set(null);
}

export function updateCachedSetting(path: string, value: unknown): void {
    const current = get(settingsCache);
    if (!current) return;

    const updated = { ...current } as Record<string, unknown>;
    const pathParts = path.split('.');
    let target = updated;

    for (let i = 0; i < pathParts.length - 1; i++) {
        const part = pathParts[i];
        if (!target[part] || typeof target[part] !== 'object') {
            target[part] = {};
        }
        target = target[part] as Record<string, unknown>;
    }

    target[pathParts[pathParts.length - 1]] = value;
    setCachedSettings(updated as UserSettings);
}

if (browser) {
    const cached = getCachedSettings();
    if (cached) {
        settingsCache.set(cached);
    }
}
