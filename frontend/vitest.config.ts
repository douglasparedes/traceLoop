import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    // Playwright browser specs live in ./smoke and run via `playwright test`,
    // never under vitest (they need real browsers + a running server).
    exclude: ["smoke/**", "node_modules/**"],
  },
});
