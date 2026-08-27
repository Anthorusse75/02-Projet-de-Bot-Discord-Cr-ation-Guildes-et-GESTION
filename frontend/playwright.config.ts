import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e', timeout: 30_000, fullyParallel: true,
  forbidOnly: Boolean(process.env.CI), retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['junit', { outputFile: 'test-results/stage07-e2e.xml' }]],
  use: { baseURL: 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 4173', url: 'http://127.0.0.1:4173', reuseExistingServer: !process.env.CI },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
