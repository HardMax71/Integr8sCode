import { defineConfig, devices } from '@playwright/test';

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
  reporter: process.env.CI ? [['html'], ['github']] : 'html',
  use: {
    baseURL: 'https://localhost:5001',
    ignoreHTTPSErrors: true,
    trace: 'on',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  // In CI, frontend runs via docker-compose; locally, start dev server if needed
  webServer: process.env.CI ? undefined : {
    command: 'npm run dev',
    url: 'https://localhost:5001',
    reuseExistingServer: true,
    ignoreHTTPSErrors: true,
    timeout: 120000,
  },
});
