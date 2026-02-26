import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import pkg from './package.json' with { type: 'json' };

// --8<-- [start:config]
export default defineConfig({
  plugins: [
    svelte({ hot: !process.env.VITEST }),
    svelteTesting(),
  ],
  test: {
    environment: 'jsdom',
    pool: 'threads',
    maxWorkers: 8,
    minWorkers: 2,
    isolate: false,
    css: false,
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.{test,spec}.{js,ts}'],
    globals: true,
    environmentMatchGlobs: [
      ['src/lib/**/*.test.ts', 'node'],
      ['src/stores/**/*.test.ts', 'node'],
      ['src/utils/**/*.test.ts', 'node'],
    ],
    deps: {
      optimizer: {
        web: {
          include: Object.keys(pkg.dependencies),
        },
      },
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      include: ['src/**/*.{ts,svelte}'],
      exclude: [
        'src/lib/api/**',
        'src/**/*.test.ts',
        'src/**/__tests__/**',
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
      $test: '/src/__tests__',
    },
  },
});
// --8<-- [end:config]
