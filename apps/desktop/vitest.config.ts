import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// A standalone config (not merged with vite.config.ts) -- the Tauri dev
// server settings there (fixed port, HMR websocket) are irrelevant to
// running component tests under jsdom.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: false,
    // e2e/ specs are mocha-framework WebdriverIO specs (`pnpm run e2e`),
    // not vitest specs -- vitest's default include glob would otherwise
    // also pick them up and fail on the missing `describe` global.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
