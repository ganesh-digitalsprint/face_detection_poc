import { defineConfig } from '@playwright/test';

// End-to-end tests run against the already-running dev stack (frontend :3000 and the backends). See docs/face_mask/README.md.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  reporter: [['list']],
  use: { baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000', headless: true, viewport: { width: 1366, height: 800 } },
});
