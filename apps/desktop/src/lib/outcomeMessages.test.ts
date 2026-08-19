import { describe, expect, it } from "vitest";
import type { BatchApplyResultView, ManagedRootUnavailableResultView } from "@file-agent/desktop-types";
import type { RustOutcome } from "../desktop";
import { completionPresentation, guidanceForOutcome } from "./outcomeMessages";

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

const MANAGED_ROOT_UNAVAILABLE: ManagedRootUnavailableResultView = {
  outcome: "managed_root_unavailable",
  message: {
    title: "No pudimos organizar esta carpeta.",
    detail: "No encontramos esta carpeta en este momento.",
    severity: "error",
    suggestedAction: "none",
  },
};

type ApplyOutcome = RustOutcome<BatchApplyResultView | ManagedRootUnavailableResultView>;

describe("completionPresentation", () => {
  // Test A
  it("classifies unknown_mutation_outcome as unknown", () => {
    const outcome: ApplyOutcome = { outcome: "unknown_mutation_outcome" };
    expect(completionPresentation(outcome)).toEqual({ kind: "unknown" });
  });

  it("A: unknown notice uses the existing UNKNOWN apply guidance verbatim", () => {
    const outcome: ApplyOutcome = { outcome: "unknown_mutation_outcome" };
    const guidance = guidanceForOutcome(outcome, "apply");
    expect(guidance).toEqual({
      title: "No pudimos confirmar si la operación terminó.",
      detail: "Revisa el historial para confirmar qué se organizó antes de intentarlo de nuevo.",
    });
  });

  // Test B
  it("classifies product_error as known_no_result, not unknown", () => {
    const outcome: ApplyOutcome = {
      outcome: "product_error",
      kind: "validation",
      code: "x",
      message: "No se pudo completar.",
    };
    const presentation = completionPresentation(outcome);
    expect(presentation.kind).toBe("known_no_result");
    if (presentation.kind === "known_no_result") {
      expect(presentation.message.title).toBe("No se pudo completar la acción.");
      expect(presentation.message.detail).toBe("No se pudo completar.");
    }
  });

  // Test C
  it("classifies retryable_interrupted as known_no_result, not unknown", () => {
    const outcome: ApplyOutcome = { outcome: "retryable_interrupted" };
    const presentation = completionPresentation(outcome);
    expect(presentation.kind).toBe("known_no_result");
    if (presentation.kind === "known_no_result") {
      expect(presentation.message.title).toBe("Se interrumpió la conexión antes de empezar.");
    }
  });

  it("classifies transport_unavailable as known_no_result, not unknown", () => {
    const outcome: ApplyOutcome = { outcome: "transport_unavailable", message: "no disponible" };
    const presentation = completionPresentation(outcome);
    expect(presentation.kind).toBe("known_no_result");
  });

  // Test D
  it("classifies ok + managed_root_unavailable as known_no_result, rendering the DTO's own message verbatim", () => {
    const outcome: ApplyOutcome = { outcome: "ok", result: MANAGED_ROOT_UNAVAILABLE };
    const presentation = completionPresentation(outcome);
    expect(presentation).toEqual({ kind: "known_no_result", message: MANAGED_ROOT_UNAVAILABLE.message });
  });

  it("classifies ok + BatchApplyResultView as result", () => {
    const outcome: ApplyOutcome = { outcome: "ok", result: RESULT };
    expect(completionPresentation(outcome)).toEqual({ kind: "result", result: RESULT });
  });
});
