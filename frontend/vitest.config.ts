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
      exclude: ['src/lib/api/**', 'src/**/*.test.ts'],
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
