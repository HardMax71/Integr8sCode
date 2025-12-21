import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,  // Reduced: 1 retry is enough to catch flakes
  workers: process.env.CI ? 2 : undefined,  // Increased: tests are independent
  timeout: 30000,  // 30s is plenty for page operations
  expect: {
    timeout: 5000,  // 5s for element expectations
  },
  reporter: process.env.CI ? [['html'], ['github']] : 'html',
  use: {
    baseURL: 'https://localhost:5001',
    ignoreHTTPSErrors: true,
    trace: 'on-first-retry',
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
