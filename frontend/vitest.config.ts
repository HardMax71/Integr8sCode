import { defineConfig } from 'vitest/config';
import { sveltekit } from '@sveltejs/kit/vite';
import { svelteTesting } from '@testing-library/svelte/vite';

// Worker threads take the zone from the process, so test.env would come too late
process.env.TZ = 'UTC';

// --8<-- [start:config]
export default defineConfig({
  plugins: [
    sveltekit(),
    svelteTesting(),
  ],
  test: {
    pool: 'threads',
    maxWorkers: process.env.CI ? 4 : 8,
    isolate: true,
    css: false,
    testTimeout: 10_000,
    mockReset: true,
    restoreMocks: true,
    unstubGlobals: true,
    environment: 'happy-dom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.{test,spec}.{js,ts}'],
    deps: {
      optimizer: {
        client: {
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
  },
});
// --8<-- [end:config]
