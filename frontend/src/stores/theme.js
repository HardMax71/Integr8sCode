import { writable, get } from 'svelte/store';

// Standard check for browser environment
const browser = typeof window !== 'undefined' && typeof document !== 'undefined';
const defaultTheme = 'auto'; // 'light', 'dark', or 'auto'
const storageKey = 'app-theme';

// Function to get system theme preference
function getSystemTheme() {
  if (!browser) return 'light';
  
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

// Function to get the initial theme based on storage, system preference, or default
function getInitialTheme() {
  if (!browser) return defaultTheme; // Default on server

  const storedTheme = localStorage.getItem(storageKey);
  if (storedTheme && ['light', 'dark', 'auto'].includes(storedTheme)) {
    return storedTheme;
  }

  return defaultTheme; // Default to 'auto'
}

// Create the writable store
const initialTheme = getInitialTheme();
const { subscribe, set: internalSet, update } = writable(initialTheme);

// Import dependencies dynamically to avoid circular imports
let saveThemeSetting;
let isAuthenticatedStore;
if (browser) {
  Promise.all([
    import('../lib/user-settings.js'),
    import('./auth.js')
  ]).then(([userSettings, auth]) => {
    saveThemeSetting = userSettings.saveThemeSetting;
    isAuthenticatedStore = auth.isAuthenticated;
  });
}

// Custom theme store that saves locally and to backend if authenticated
export const theme = {
  subscribe,
  set: (value) => {
    internalSet(value);
    // Always save locally
    if (browser) {
      localStorage.setItem(storageKey, value);
    }
    // Save to backend if authenticated
    if (saveThemeSetting && isAuthenticatedStore && get(isAuthenticatedStore)) {
      saveThemeSetting(value);
    }
  },
  update
};

// Function to apply the theme class to the document element
function applyTheme(newTheme) {
  if (!browser) return;

  const root = document.documentElement;
  let effectiveTheme = newTheme;
  
  // If theme is auto, use the actual system preference
  if (newTheme === 'auto') {
    effectiveTheme = getSystemTheme();
  }
  
  const isDark = effectiveTheme === 'dark';

  root.classList.toggle('dark', isDark);
  // Don't save to localStorage here - it's handled in the store's set method
}

// Subscribe to changes in the store and apply the theme
theme.subscribe(applyTheme);

// Initialize the theme on first load
if (browser) {
   applyTheme(initialTheme);
   
   // Listen for system theme changes
   if (window.matchMedia) {
     const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
     mediaQuery.addEventListener('change', (e) => {
       // Only update if current theme is 'auto'
       theme.update(currentTheme => {
         if (currentTheme === 'auto') {
           // Trigger re-apply by setting to same value
           applyTheme('auto');
         }
         return currentTheme;
       });
     });
   }
}

// Function to toggle theme (can be called from a button)
export function toggleTheme() {
    const currentTheme = get(theme);
    let newTheme;
    
    // Cycle through: light -> dark -> auto -> light
    if (currentTheme === 'light') {
        newTheme = 'dark';
    } else if (currentTheme === 'dark') {
        newTheme = 'auto';
    } else {
        newTheme = 'light';
    }
    
    theme.set(newTheme);
}

// Function to set a specific theme
export function setTheme(newTheme) {
    if (['light', 'dark', 'auto'].includes(newTheme)) {
        theme.set(newTheme);
    }
}