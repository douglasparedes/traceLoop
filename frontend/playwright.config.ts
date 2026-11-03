import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./smoke",
  timeout: 120_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: process.env.SMOKE_BASE_URL || "http://localhost:8000",
  },
  // Single chromium project: the smoke suite proves the guided loop works
  // in a real browser (server state + UI), not across engines.
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
