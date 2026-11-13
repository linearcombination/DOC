import type { PlaywrightTestConfig } from '@playwright/test'

const config: PlaywrightTestConfig = {
  testDir: 'tests',
  testMatch: '**/*.ts',
  workers: process.env.CI ? 2 : undefined,
  globalTimeout: process.env.CI ? 30 * 60 * 1000 : undefined, // 30 min suite cap
  timeout: process.env.CI ? 80000 : 60000,
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  expect: {
    // Assertion timeout separate from test timeout
    timeout: 15000
  },
  use: {
    // Navigation/action timeout — how long Playwright waits for a single action
    actionTimeout: 30000,
    navigationTimeout: 30000
  }
}

export default config
