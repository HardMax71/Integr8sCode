import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';

// --8<-- [start:config]
export default defineConfig({
  plugins: [
    svelte({ hot: !process.env.VITEST }),
    svelteTesting(),
  ],
  test: {
    pool: 'threads',
    maxWorkers: process.env.CI ? 4 : 8,
    minWorkers: process.env.CI ? 4 : 2,
    isolate: false,
    css: false,
    testTimeout: 10_000,
    environment: 'happy-dom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.{test,spec}.{js,ts}'],
    deps: {
      optimizer: {
        web: {
          include: ['svelte', '@lucide/svelte', 'date-fns', 'dompurify', 'ansi_up', 'svelte-sonner'],
        },
      },
    },
    coverage: {
      provider: 'v8',
      reporter: process.env.CI ? ['text', 'lcov'] : ['text', 'html', 'lcov'],
      include: ['src/**/*.{ts,svelte}'],
      exclude: [
        'src/lib/api/**',
        'src/**/*.test.ts',
        'src/**/__tests__/**',
        'src/**/index.ts',
      ],
      thresholds: {
        statements: 92,
        branches: 76,
        functions: 90,
        lines: 92,
      },
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
      $test: '/src/__tests__',
    },
  },
});
// --8<-- [end:config]
