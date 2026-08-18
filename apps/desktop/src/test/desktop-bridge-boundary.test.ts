import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Mirrors the Python side's AST-guardrail convention
// (tests/desktop_api/test_dependency_boundary.py): a plain source-text
// scan proving no file outside src/desktop/ imports a Tauri frontend
// package directly. eslint.config.js enforces this too during `pnpm
// lint`; this test gives the same guarantee independent of lint tooling.

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, "..");

function walk(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "desktop") continue;
      files.push(...walk(full));
    } else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name)) {
      // Test files legitimately import Tauri packages to mock them
      // (vi.mock("@tauri-apps/...")) -- this guardrail is about
      // PRODUCTION code only, matching the design's own scope.
      files.push(full);
    }
  }
  return files;
}

describe("desktop/ Tauri import boundary", () => {
  it("no file outside src/desktop imports a Tauri package", () => {
    const offenders: string[] = [];
    for (const file of walk(srcRoot)) {
      const contents = readFileSync(file, "utf-8");
      if (/from ["']@tauri-apps\//.test(contents)) {
        offenders.push(file);
      }
    }
    expect(offenders).toEqual([]);
  });
});
