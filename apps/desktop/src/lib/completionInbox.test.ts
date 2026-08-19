import { describe, expect, it } from "vitest";
import type { RustOutcome } from "../desktop";
import type { BatchApplyResultView } from "@file-agent/desktop-types";
import { appendCompletion, MAX_ORDINARY_NOTICES, removeCompletion, type RetainedCompletion } from "./completionInbox";

const RESULT: BatchApplyResultView = {
  outcome: "ok",
  batchId: "batch-1",
  status: "completed",
  startedAt: "2026-01-01T00:00:00Z",
  completedAt: "2026-01-01T00:00:01Z",
  managedRootId: "root-1",
  items: [],
  summary: { selected: 1, processed: 1, applied: 1, notApplied: 0, skipped: 0, invalid: 0 },
  summaryMessage: {
    title: "1 archivos se organizaron correctamente.",
    detail: "Todos los archivos seleccionados se movieron a su carpeta.",
    severity: "info",
    suggestedAction: "none",
  },
};

let counter = 0;
function ordinaryEntry(): RetainedCompletion {
  counter += 1;
  const outcome: RustOutcome<BatchApplyResultView> = { outcome: "ok", result: RESULT };
  return { id: `ordinary-${counter}`, managedRootId: "root-1", outcome, receivedAt: counter };
}
function unknownEntry(): RetainedCompletion {
  counter += 1;
  const outcome: RustOutcome<BatchApplyResultView> = { outcome: "unknown_mutation_outcome" };
  return { id: `unknown-${counter}`, managedRootId: "root-1", outcome, receivedAt: counter };
}

describe("completion inbox retention", () => {
  // Test E
  it("evicts only the oldest ordinary notice when a 6th ordinary notice arrives", () => {
    let list: RetainedCompletion[] = [];
    const entries = Array.from({ length: MAX_ORDINARY_NOTICES }, () => ordinaryEntry());
    for (const e of entries) list = appendCompletion(list, e);
    expect(list).toHaveLength(5);

    const sixth = ordinaryEntry();
    list = appendCompletion(list, sixth);

    expect(list).toHaveLength(5);
    expect(list.map((e) => e.id)).not.toContain(entries[0].id);
    expect(list.map((e) => e.id)).toContain(sixth.id);
  });

  // Test F
  it("evicts only among the ordinary subset; an UNKNOWN entry always survives", () => {
    let list: RetainedCompletion[] = [];
    const ordinaries = Array.from({ length: MAX_ORDINARY_NOTICES }, () => ordinaryEntry());
    for (const e of ordinaries) list = appendCompletion(list, e);
    const unknown = unknownEntry();
    list = appendCompletion(list, unknown);
    expect(list).toHaveLength(6);

    const sixthOrdinary = ordinaryEntry();
    list = appendCompletion(list, sixthOrdinary);

    expect(list).toHaveLength(6);
    expect(list.map((e) => e.id)).toContain(unknown.id);
    expect(list.map((e) => e.id)).not.toContain(ordinaries[0].id);
    const ordinaryIds = list.filter((e) => e.id !== unknown.id).map((e) => e.id);
    expect(ordinaryIds).toHaveLength(5);
  });

  // Test G
  it("never auto-evicts or replaces one UNKNOWN entry with another", () => {
    let list: RetainedCompletion[] = [];
    const first = unknownEntry();
    const second = unknownEntry();
    list = appendCompletion(list, first);
    list = appendCompletion(list, second);
    expect(list.map((e) => e.id)).toEqual([first.id, second.id]);

    // Even past the ordinary cap, unknowns keep accumulating untouched.
    for (let i = 0; i < MAX_ORDINARY_NOTICES + 2; i += 1) {
      list = appendCompletion(list, unknownEntry());
    }
    expect(list.filter((e) => e.id === first.id || e.id === second.id)).toHaveLength(2);

    list = removeCompletion(list, first.id);
    expect(list.map((e) => e.id)).not.toContain(first.id);
    expect(list.map((e) => e.id)).toContain(second.id);
  });

  it("removeCompletion removes only the exact entry requested", () => {
    let list: RetainedCompletion[] = [];
    const a = ordinaryEntry();
    const b = unknownEntry();
    list = appendCompletion(list, a);
    list = appendCompletion(list, b);

    list = removeCompletion(list, a.id);
    expect(list.map((e) => e.id)).toEqual([b.id]);
  });
});
