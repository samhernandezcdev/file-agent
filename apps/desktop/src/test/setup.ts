import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// `globals: false` in vitest.config.ts means React Testing Library's own
// auto-cleanup detection (which looks for a global `afterEach`) never
// fires -- without this, every test's rendered tree would stack up in
// the same jsdom document, producing "found multiple elements" failures
// from the SECOND test in any file onward.
afterEach(() => {
  cleanup();
});
