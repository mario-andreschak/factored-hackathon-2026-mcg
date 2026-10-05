import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.AVATAR_E2E_URL || 'http://127.0.0.1:4317',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: 'chromium', use: {
    browserName: 'chromium',
    // Windows uses the already installed browser. CI can use Playwright Chromium.
    channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined),
  } }],
  webServer: process.env.AVATAR_E2E_URL ? undefined : {
    command: 'npm run dev',
    url: 'http://127.0.0.1:4317',
    reuseExistingServer: true,
    timeout: 60_000,
    // New test servers never have a provider key, even if the shell does.
    env: { OPENAI_API_KEY: '', GEMINI_API_KEY: '', GOOGLE_API_KEY: '', OPENROUTER_API_KEY: '', AVATAR_VOICE_PROVIDER: 'none', SAVIA_UPSTREAM: process.env.AVATAR_E2E_SAVIA || process.env.SAVIA_UPSTREAM || '' },
  },
});
