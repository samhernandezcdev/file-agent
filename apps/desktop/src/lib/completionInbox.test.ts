import { describe, expect, it } from "vitest";
import type { RustOutcome } from "../desktop";
import type { BatchApplyResultView } from "@file-agent/desktop-types";
import { appendCompletion, MAX_ORDINARY_NOTICES, removeCompletion, type RetainedCompletion } from "./completionInbox";
import { completionPresentation, type ApplyOutcome } from "./outcomeMessages";

const isOrdinary = (entry: RetainedCompletion<ApplyOutcome>) =>
  completionPresentation(entry.outcome).kind !== "unknown";

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
function ordinaryEntry(): RetainedCompletion<ApplyOutcome> {
  counter += 1;
  const outcome: RustOutcome<BatchApplyResultView> = { outcome: "ok", result: RESULT };
  return { id: `ordinary-${counter}`, correlationId: "root-1", outcome, receivedAt: counter };
}
function unknownEntry(): RetainedCompletion<ApplyOutcome> {
  counter += 1;
  const outcome: RustOutcome<BatchApplyResultView> = { outcome: "unknown_mutation_outcome" };
  return { id: `unknown-${counter}`, correlationId: "root-1", outcome, receivedAt: counter };
}

describe("completion inbox retention", () => {
  // Test E
  it("evicts only the oldest ordinary notice when a 6th ordinary notice arrives", () => {
    let list: RetainedCompletion<ApplyOutcome>[] = [];
    const entries = Array.from({ length: MAX_ORDINARY_NOTICES }, () => ordinaryEntry());
    for (const e of entries) list = appendCompletion(list, e, isOrdinary);
    expect(list).toHaveLength(5);

    const sixth = ordinaryEntry();
    list = appendCompletion(list, sixth, isOrdinary);

    expect(list).toHaveLength(5);
    expect(list.map((e) => e.id)).not.toContain(entries[0].id);
    expect(list.map((e) => e.id)).toContain(sixth.id);
  });

  // Test F
  it("evicts only among the ordinary subset; an UNKNOWN entry always survives", () => {
    let list: RetainedCompletion<ApplyOutcome>[] = [];
    const ordinaries = Array.from({ length: MAX_ORDINARY_NOTICES }, () => ordinaryEntry());
    for (const e of ordinaries) list = appendCompletion(list, e, isOrdinary);
    const unknown = unknownEntry();
    list = appendCompletion(list, unknown, isOrdinary);
    expect(list).toHaveLength(6);

    const sixthOrdinary = ordinaryEntry();
    list = appendCompletion(list, sixthOrdinary, isOrdinary);

    expect(list).toHaveLength(6);
    expect(list.map((e) => e.id)).toContain(unknown.id);
    expect(list.map((e) => e.id)).not.toContain(ordinaries[0].id);
    const ordinaryIds = list.filter((e) => e.id !== unknown.id).map((e) => e.id);
    expect(ordinaryIds).toHaveLength(5);
  });

  // Test G
  it("never auto-evicts or replaces one UNKNOWN entry with another", () => {
    let list: RetainedCompletion<ApplyOutcome>[] = [];
    const first = unknownEntry();
    const second = unknownEntry();
    list = appendCompletion(list, first, isOrdinary);
    list = appendCompletion(list, second, isOrdinary);
    expect(list.map((e) => e.id)).toEqual([first.id, second.id]);

    // Even past the ordinary cap, unknowns keep accumulating untouched.
    for (let i = 0; i < MAX_ORDINARY_NOTICES + 2; i += 1) {
      list = appendCompletion(list, unknownEntry(), isOrdinary);
    }
    expect(list.filter((e) => e.id === first.id || e.id === second.id)).toHaveLength(2);

    list = removeCompletion(list, first.id);
    expect(list.map((e) => e.id)).not.toContain(first.id);
    expect(list.map((e) => e.id)).toContain(second.id);
  });

  it("removeCompletion removes only the exact entry requested", () => {
    let list: RetainedCompletion<ApplyOutcome>[] = [];
    const a = ordinaryEntry();
    const b = unknownEntry();
    list = appendCompletion(list, a, isOrdinary);
    list = appendCompletion(list, b, isOrdinary);

    list = removeCompletion(list, a.id);
    expect(list.map((e) => e.id)).toEqual([b.id]);
  });

  // FA-017.4 §9/Part 24 "completion-inbox regression": the FIFO/eviction
  // mechanics are now generic over TOutcome and driven entirely by the
  // caller-supplied classifier -- these two prove a destination-setup
  // outcome list behaves identically under the same generic functions,
  // with its own independent classifier, never sharing state or cap
  // accounting with an apply list.
  it("appendCompletion works identically for a non-apply outcome shape given its own classifier", () => {
    type FakeOutcome = { outcome: "ok" | "unknown_mutation_outcome" };
    const fakeIsOrdinary = (entry: RetainedCompletion<FakeOutcome>) => entry.outcome.outcome !== "unknown_mutation_outcome";
    let list: RetainedCompletion<FakeOutcome>[] = [];
    for (let i = 0; i < MAX_ORDINARY_NOTICES; i += 1) {
      list = appendCompletion(
        list,
        { id: `fake-${i}`, correlationId: "root-1", outcome: { outcome: "ok" }, receivedAt: i },
        fakeIsOrdinary,
      );
    }
    expect(list).toHaveLength(MAX_ORDINARY_NOTICES);
    list = appendCompletion(
      list,
      { id: "fake-extra", correlationId: "root-1", outcome: { outcome: "ok" }, receivedAt: 99 },
      fakeIsOrdinary,
    );
    expect(list).toHaveLength(MAX_ORDINARY_NOTICES);
    expect(list.map((e) => e.id)).not.toContain("fake-0");
  });

  it("two independently-typed lists never influence each other's cap accounting", () => {
    let applyList: RetainedCompletion<ApplyOutcome>[] = [];
    type FakeOutcome = { outcome: "ok" | "unknown_mutation_outcome" };
    const fakeIsOrdinary = (entry: RetainedCompletion<FakeOutcome>) => entry.outcome.outcome !== "unknown_mutation_outcome";
    let otherList: RetainedCompletion<FakeOutcome>[] = [];

    for (let i = 0; i < MAX_ORDINARY_NOTICES; i += 1) {
      applyList = appendCompletion(applyList, ordinaryEntry(), isOrdinary);
    }
    otherList = appendCompletion(
      otherList,
      { id: "other-1", correlationId: "root-2", outcome: { outcome: "ok" }, receivedAt: 1 },
      fakeIsOrdinary,
    );

    expect(applyList).toHaveLength(MAX_ORDINARY_NOTICES);
    expect(otherList).toHaveLength(1);
  });
});
