import { writable } from 'svelte/store';

// Standard check for browser environment
const browser = typeof window !== 'undefined' && typeof document !== 'undefined';
const defaultTheme = 'system'; // 'light', 'dark', or 'system'
const storageKey = 'app-theme';

// Function to get the initial theme based on storage, system preference, or default
function getInitialTheme() {
  if (!browser) return defaultTheme; // Default on server

  const storedTheme = localStorage.getItem(storageKey);
  if (storedTheme && ['light', 'dark'].includes(storedTheme)) {
    return storedTheme;
  }

  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light'; // Fallback to light if system preference isn't dark or not supported
}

// Create the writable store
const initialTheme = getInitialTheme();
export const theme = writable(initialTheme);

// Function to apply the theme class to the document element
function applyTheme(newTheme) {
  if (!browser) return;

  const root = document.documentElement;
  const isDark = newTheme === 'dark';

  root.classList.toggle('dark', isDark);
  localStorage.setItem(storageKey, newTheme);
}

// Subscribe to changes in the store and apply the theme
theme.subscribe(applyTheme);

// Initialize the theme on first load
if (browser) {
   applyTheme(initialTheme);
}

// Function to toggle theme (can be called from a button)
export function toggleTheme() {
    theme.update(currentTheme => {
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        return newTheme;
    });
}

// Function to set a specific theme
export function setTheme(newTheme) {
    if (['light', 'dark'].includes(newTheme)) {
        theme.set(newTheme);
    }
}