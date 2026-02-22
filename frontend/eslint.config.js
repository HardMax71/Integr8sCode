import eslint from '@eslint/js';
import tseslint from '@typescript-eslint/eslint-plugin';
import tsparser from '@typescript-eslint/parser';
import svelte from 'eslint-plugin-svelte';
import svelteParser from 'svelte-eslint-parser';
import globals from 'globals';

// Svelte 5 runes
const svelteRunes = {
  $state: 'readonly',
  $derived: 'readonly',
  $effect: 'readonly',
  $props: 'readonly',
  $bindable: 'readonly',
  $inspect: 'readonly',
  $host: 'readonly',
};

export default [
  eslint.configs.recommended,
  {
    files: ['src/**/*.ts'],
    ignores: ['**/__tests__/**', '**/tests/**'],
    languageOptions: {
      parser: tsparser,
      parserOptions: {
        ecmaVersion: 2022,
        sourceType: 'module',
        project: './tsconfig.json',
      },
      globals: {
        ...globals.browser,
        ...globals.node,
        ...svelteRunes,
      },
    },
    plugins: {
      '@typescript-eslint': tseslint,
    },
    rules: {
      ...tseslint.configs['strict-type-checked'].rules,
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/only-throw-error': 'off', // API client returns unknown errors
      '@typescript-eslint/no-non-null-assertion': 'off', // Needed with noUncheckedIndexedAccess
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],
      'no-unused-vars': 'off',
    },
  },
  {
    files: ['src/**/*.svelte'],
    languageOptions: {
      parser: svelteParser,
      parserOptions: {
        parser: tsparser,
      },
      globals: {
        ...globals.browser,
        ...svelteRunes,
      },
    },
    plugins: {
      svelte,
    },
    rules: {
      ...svelte.configs.recommended.rules,
      'svelte/button-has-type': 'warn',
      'no-unused-vars': 'off',
      'no-undef': 'off',
    },
  },
  {
    ignores: [
      'public/',
      'node_modules/',
      '*.config.js',
      'playwright-report/',
      'e2e/',
      'src/lib/api/', // Generated API client
      '**/__tests__/**', // Test files
    ],
  },
];
