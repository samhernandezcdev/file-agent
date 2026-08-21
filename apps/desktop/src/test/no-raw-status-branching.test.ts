/**
 * FA-017.3: static regression guard -- React must not interpret internal
 * reason codes / raw status strings for product meaning or authorization-
 * like behavior. Reads the actual source of the product-facing screens
 * this ticket touched and asserts no line branches on a raw `.status`/
 * `.reasonCode` comparison.
 *
 * Deliberately narrow and file-scoped (not a general linter) -- it names
 * the exact files/patterns this ticket's design forbids, mirroring the
 * Python-side AST guardrails' spirit without needing a real TS parser.
 * `planStatusPresentation.ts` is NOT covered here: its own module
 * docstring documents that it keys off raw status only for icon/color
 * (never text, never behavior), an explicitly accepted narrow exception
 * (see FA-017.3 design round 1 §1.8).
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const GUARDED_FILES = [
  "features/organization-plan/PlanScreen.tsx",
  "features/organization-plan/ConflictSummary.tsx",
  "features/apply/ApplyResultsScreen.tsx",
  "features/history/HistoryScreen.tsx",
  "features/history/HistoryDetailScreen.tsx",
  "components/ui/UndoCompletionNotice.tsx",
];

// A raw product-status/reason-code comparison used to decide behavior --
// e.g. `item.status === "review_required"`, `item.reasonCode === "..."`.
// Does NOT match RustOutcome/transport-level discriminants (`outcome ===
// "ok"`, `result.outcome === "found"`, etc.), which are a completely
// different, legitimate boundary (product_error/unknown_mutation_outcome/
// managed_root_unavailable) this ticket does not touch.
const FORBIDDEN_PATTERNS: RegExp[] = [
  /\.status\s*===\s*"(?!ok|found|completed|incomplete|unavailable)/,
  /\.reasonCode\b/,
  /\breason_code\b/,
];

function readSource(relativePath: string): string {
  return readFileSync(resolve(SRC_ROOT, relativePath), "utf-8");
}

describe("no raw product-status/reason-code branching in React", () => {
  it.each(GUARDED_FILES)("%s contains no forbidden pattern", (relativePath) => {
    const source = readSource(relativePath);
    const offendingLines = source
      .split("\n")
      .map((line, index) => ({ line, number: index + 1 }))
      // Skip comment lines (JSDoc/block-comment continuations starting
      // with "*", or "//" line comments) -- this guard is about actual
      // code branching, not prose that happens to mention the word (e.g.
      // documenting that a field is deliberately absent).
      .filter(({ line }) => !/^\s*(\*|\/\/)/.test(line))
      .filter(({ line }) => FORBIDDEN_PATTERNS.some((pattern) => pattern.test(line)));

    expect(
      offendingLines,
      `forbidden raw status/reasonCode usage in ${relativePath}:\n${offendingLines
        .map(({ line, number }) => `  L${number}: ${line.trim()}`)
        .join("\n")}`,
    ).toEqual([]);
  });

  it("PlanScreen uses needsReviewAction, not a raw status comparison, to gate Aprobar/Omitir", () => {
    const source = readSource("features/organization-plan/PlanScreen.tsx");
    expect(source).toContain("needsReviewAction");
  });

  it("HistoryDetailScreen uses undoAvailable/alreadyUndone, not a raw status/transactionId comparison, to gate Deshacer", () => {
    const source = readSource("features/history/HistoryDetailScreen.tsx");
    expect(source).toContain("undoAvailable");
    expect(source).toContain("alreadyUndone");
    expect(source).not.toMatch(/item\.status\s*===\s*"applied"/);
  });

  // FA-017.5 Part 9: SUMMARY NAVIGATION != FILESYSTEM MUTATION -- the
  // compact card never renders a Deshacer/mutation trigger, and never
  // reads undoAvailable/alreadyUndone at all (it only ever renders the
  // already-composed recoveryMessage opaquely).
  it("HistoryScreen never renders a Deshacer action or reads item-level undo facts", () => {
    const source = readSource("features/history/HistoryScreen.tsx");
    expect(source).not.toContain("undoAvailable");
    expect(source).not.toContain("alreadyUndone");
    expect(source).not.toMatch(/Deshacer/);
  });

  it("HistoryScreen and HistoryDetailScreen never derive BatchRecoveryState meaning themselves", () => {
    for (const path of ["features/history/HistoryScreen.tsx", "features/history/HistoryDetailScreen.tsx"]) {
      const source = readSource(path);
      expect(source).not.toMatch(/recoveryMessage\s*===\s*"/);
      expect(source).not.toMatch(/\brecoveryState\b/);
    }
  });

  // FA-017.6 Design Round 3 (R3-1.E/F): the compact context bar and sticky
  // action footer are plain CSS `position: sticky`, always in the DOM --
  // zero scroll listeners, zero IntersectionObserver, zero scroll-position
  // React state. A static source check, since jsdom (used by every other
  // PlanScreen test) does not compute real sticky/scroll geometry, so this
  // is the correct place to prove the "no scroll JS" architectural
  // guarantee rather than a behavioral one.
  it("PlanScreen introduces no scroll listener, IntersectionObserver, or scroll-tracking state for its sticky surfaces", () => {
    const source = readSource("features/organization-plan/PlanScreen.tsx");
    // Comment lines are exempt -- this file's own docstrings document the
    // absence of these patterns, which would otherwise trip a naive
    // whole-file match (same comment-skipping discipline the forbidden-
    // pattern check above already uses).
    const codeOnly = source
      .split("\n")
      .filter((line) => !/^\s*(\*|\/\/)/.test(line))
      .join("\n");
    expect(codeOnly).not.toMatch(/addEventListener\(\s*["']scroll["']/);
    expect(codeOnly).not.toMatch(/IntersectionObserver/);
    expect(codeOnly).not.toMatch(/scrollY|scrollTop|getBoundingClientRect/);
  });
});
