/** @type {import('tailwindcss').Config} */
const colors = require('tailwindcss/colors');

// Use module.exports for .cjs files
module.exports = {
  content: [
    './src/**/*.{html,js,svelte,ts}',
    './public/index.html' // Make sure this points to your actual index.html if different
  ],
  darkMode: 'class', // Enable class-based dark mode
  theme: {
    extend: {
      colors: {
        primary: { // Main interactive color - Blue
          light: colors.blue[400], // #60a5fa
          DEFAULT: colors.blue[500], // #3b82f6
          dark: colors.blue[600],   // #2563eb
        },
        secondary: { // Accent color - Teal
          light: colors.teal[300], // #5eead4
          DEFAULT: colors.teal[500], // #14b8a6
          dark: colors.teal[700],   // #0f766e
        },
        neutral: colors.slate, // Using Slate for a cooler neutral palette
        // Custom semantic colors for light theme
        'bg-default': colors.slate[50],       // Light background
        'bg-alt': colors.white,             // Slightly different bg (cards, inputs)
        'bg-sidebar': colors.slate[100],      // Sidebar/distinct area bg
        'fg-default': colors.slate[800],      // Default text
        'fg-muted': colors.slate[500],       // Muted text
        'fg-subtle': colors.slate[400],      // Very subtle text/borders
        'border-default': colors.slate[200],    // Default borders
        'border-input': colors.slate[300],     // Input borders
        'focus-ring': colors.blue[300],       // Focus ring color

        // Custom semantic colors for dark theme (using 'dark:' variants is preferred)
        'dark-bg-default': colors.slate[900],
        'dark-bg-alt': colors.slate[800],
        'dark-bg-sidebar': colors.slate[950], // Even darker for contrast
        'dark-fg-default': colors.slate[200],
        'dark-fg-muted': colors.slate[400],
        'dark-fg-subtle': colors.slate[500],
        'dark-border-default': colors.slate[700],
        'dark-border-input': colors.slate[600],
        'dark-focus-ring': colors.blue[500], // Brighter focus in dark mode

        'code-bg': colors.slate[900], // CodeMirror dark background
      },
      fontFamily: {
        // Using Inter as the main UI font, Fira Code for monospace
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif', '"Apple Color Emoji"', '"Segoe UI Emoji"', '"Segoe UI Symbol"', '"Noto Color Emoji"'],
        mono: ['Fira Code', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', '"Liberation Mono"', '"Courier New"', 'monospace'],
      },
      boxShadow: {
        'input-focus': `0 0 0 3px var(--tw-shadow-color)`, // Use variable for focus ring
      },
      // Add custom transition timing if desired
      transitionTimingFunction: {
         'ease-out-expo': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      // Keyframes for potential subtle animations
      keyframes: {
        fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
        flyIn: { '0%': { opacity: '0', transform: 'translateY(10px)'}, '100%': { opacity: '1', transform: 'translateY(0)'}}
      },
      animation: {
        fadeIn: 'fadeIn 0.3s ease-out',
        flyIn: 'flyIn 0.3s ease-out-expo', // Using custom ease
      }
    },
  },
  plugins: [
    // Use require for CJS
    require('@tailwindcss/forms')({
      strategy: 'class', // Use class strategy for forms plugin
    }),
  ],
};