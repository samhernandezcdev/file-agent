/**
 * FA-017 E2E harness (WebdriverIO + @wdio/tauri-service).
 *
 * Prerequisite build sequence (see package.json's "e2e" script, which
 * runs these automatically):
 *   1. pnpm run build:e2e        -- VITE_E2E=true vite build (bundles
 *                                    the @wdio/tauri-plugin frontend hook)
 *   2. pnpm run build:e2e:tauri  -- tauri build --debug --no-bundle
 *                                    --features e2e-testing
 *                                    --config src-tauri/tauri.e2e.conf.json
 *   3. wdio run wdio.conf.ts
 *
 * The e2e-testing Cargo feature and the "e2e" capability (wdio:default
 * permission) are never present in a normal dev/release build -- see
 * src-tauri/Cargo.toml and tauri.e2e.conf.json.
 *
 * Isolated fixtures only: FILE_AGENT_DESKTOP_APP_DATA_ROOT points the
 * whole running app (Rust host AND the Python sidecar it spawns) at a
 * throwaway temp directory created fresh for this run -- the developer's
 * real Downloads/Documents/%APPDATA%/FileAgent are never touched.
 */
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const e2eAppDataRoot = mkdtempSync(join(tmpdir(), "file-agent-e2e-"));
process.env.FILE_AGENT_DESKTOP_APP_DATA_ROOT = e2eAppDataRoot;

export const config: WebdriverIO.Config = {
  runner: "local",
  specs: ["./e2e/**/*.spec.ts"],
  maxInstances: 1,

  services: [
    [
      "@wdio/tauri-service" as any,
      {
        appBinaryPath: "./src-tauri/target/debug/desktop.exe",
        driverProvider: "embedded",
      },
    ],
  ],

  capabilities: [
    {
      browserName: "tauri",
      "tauri:options": {
        application: "./src-tauri/target/debug/desktop.exe",
      },
    } as any,
  ],

  logLevel: "info",
  bail: 0,
  waitforTimeout: 20000,
  connectionRetryTimeout: 120000,
  connectionRetryCount: 3,

  framework: "mocha",
  reporters: ["spec"],
  mochaOpts: {
    ui: "bdd",
    timeout: 120000,
  },
};
