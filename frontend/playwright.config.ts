import { defineConfig, devices } from '@playwright/test';

// --8<-- [start:config]
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  timeout: 10000,  // 10s max per test
  expect: {
    timeout: 3000,  // 3s for assertions
  },
  reporter: [
    ...(process.env.CI ? [['list'] as const, ['html'] as const, ['github'] as const] : [['list'] as const]),
    ['monocart-reporter', {
      name: 'E2E Coverage Report',
      outputFile: 'coverage/e2e/report.html',
      coverage: {
        reports: ['v8', 'text', ['lcovonly', { outputFile: 'coverage/e2e/lcov.info' }]],
        sourceFilter: (sourcePath: string) => {
          return sourcePath.includes('/src/') &&
            !sourcePath.includes('node_modules') &&
            !sourcePath.includes('__tests__');
        },
      },
    }],
  ],
  use: {
    baseURL: 'https://localhost:5001',
    ignoreHTTPSErrors: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: process.env.CI ? undefined : {
    command: 'npm run dev',
    url: 'https://localhost:5001',
    reuseExistingServer: true,
    ignoreHTTPSErrors: true,
    timeout: 120000,
  },
});
// --8<-- [end:config]
