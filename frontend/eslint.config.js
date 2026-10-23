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
  ...svelte.configs.recommended,
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
      // tsconfig's noUnusedLocals and noUnusedParameters cover this, and know declaration merging repeats type parameters
      '@typescript-eslint/no-unused-vars': 'off',
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
    rules: {
      'svelte/button-has-type': 'error',
      'no-unused-vars': 'off',
      'no-undef': 'off',
    },
  },
  {
    // Logs go through LogTape: getLogger(['integr8scode', area]), configured once in hooks.client.ts
    files: ['src/**/*.ts', 'src/**/*.svelte'],
    rules: { 'no-console': 'error' },
  },
  {
    // An API field has one name: its key, shown through fieldTitle. A color has one name too: a token from app.css
    files: ['src/**/*.ts', 'src/**/*.svelte'],
    rules: {
      'no-restricted-syntax': [
        'error',
        ...['SvelteLiteral[value=', 'Literal[value=', 'TemplateElement[value.raw='].flatMap((node) => [
          {
            selector: String.raw`${node}/(^|\s)dark:/]`,
            message: 'The color tokens in app.css switch with .dark on their own; drop the dark: variant.',
          },
          {
            selector: String.raw`${node}/(^|[\s:])(text|bg|border|ring|divide|from|to|via|fill|stroke|outline|placeholder|decoration)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d/]`,
            message: 'Use a color token from app.css (fg, muted, accent, danger, ...), not a raw Tailwind palette color.',
          },
        ]),
        {
          selector: "CallExpression[callee.property.name=/^(accessor|display)$/] Property[key.name='header']",
          message: 'DataTable titles a column by its id; name the column after its API key instead.',
        },
        {
          selector: String.raw`SvelteElement[name.name=/^([lL]abel|dt|th)$/] SvelteText[value=/\w/]`,
          message: "Label an API field with {fieldTitle('key')}; hand-written text gives it a second name.",
        },
      ],
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
