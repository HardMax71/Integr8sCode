import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';

export default defineConfig({
  plugins: [
    svelte({ hot: !process.env.VITEST }),
    svelteTesting(),
  ],
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.{test,spec}.{js,ts}'],
    globals: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      include: ['src/**/*.{ts,svelte}'],
      exclude: [
        'src/lib/api/**',
        'src/**/*.test.ts',
        'src/**/__tests__/**',
        // Entry points & route pages — tested by E2E, not unit tests
        'src/App.svelte',
        'src/main.ts',
        'src/routes/*.svelte',
        // Editor components — tested by E2E
        'src/components/editor/**',
        // Barrel re-exports
        'src/**/index.ts',
      ],
    },
  },
  resolve: {
    conditions: ['browser'],
    alias: {
      $lib: '/src/lib',
      $components: '/src/components',
      $stores: '/src/stores',
      $routes: '/src/routes',
      $utils: '/src/utils',
      $styles: '/src/styles',
    },
  },
});
