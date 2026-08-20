import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { BatchApplyResultView } from "@file-agent/desktop-types";
import { ApplyResultsScreen } from "./ApplyResultsScreen";

function result(overrides: Partial<BatchApplyResultView["summary"]> = {}): BatchApplyResultView {
  return {
    outcome: "ok",
    batchId: "batch-1",
    status: "completed",
    startedAt: "2026-01-01T00:00:00Z",
    completedAt: "2026-01-01T00:00:01Z",
    managedRootId: "root-1",
    items: [],
    summary: { selected: 2, processed: 2, applied: 2, notApplied: 0, skipped: 0, invalid: 0, ...overrides },
    summaryMessage: {
      title: "2 archivos se organizaron correctamente.",
      detail: "Todos los archivos seleccionados se movieron a su carpeta.",
      severity: "info",
      suggestedAction: "none",
    },
  };
}

// FA-017.4 Part 13/14: full success keeps History as the trust-
// reinforcing primary action (unchanged from FA-017.1 §20); a partial or
// fully-failed batch instead promotes "Analizar de nuevo" -- and it is
// only ever rendered when a same-root reanalyze target actually resolved
// (onReanalyze !== null), falling back to "Volver a la carpeta" as the
// primary action otherwise.
describe("ApplyResultsScreen -- result continuation (FA-017.4)", () => {
  it("full success: 'Ver historial' is primary, 'Analizar de nuevo' is offered as secondary", () => {
    render(
      <ApplyResultsScreen
        result={result()}
        onViewHistory={vi.fn()}
        onDone={vi.fn()}
        onReanalyze={vi.fn()}
      />,
    );
    const buttons = screen.getAllByRole("button").map((b) => b.textContent);
    expect(buttons[0]).toBe("Ver historial");
    expect(screen.getByRole("button", { name: "Analizar de nuevo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Volver a la carpeta" })).toBeInTheDocument();
  });

  it("full success with no resolvable reanalyze target: 'Ver historial' primary, no 'Analizar de nuevo'", () => {
    render(
      <ApplyResultsScreen result={result()} onViewHistory={vi.fn()} onDone={vi.fn()} onReanalyze={null} />,
    );
    const buttons = screen.getAllByRole("button").map((b) => b.textContent);
    expect(buttons[0]).toBe("Ver historial");
    expect(screen.queryByRole("button", { name: "Analizar de nuevo" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Volver a la carpeta" })).toBeInTheDocument();
  });

  it("partial success: 'Analizar de nuevo' is primary, 'Ver historial' secondary", () => {
    render(
      <ApplyResultsScreen
        result={result({ applied: 1, notApplied: 1 })}
        onViewHistory={vi.fn()}
        onDone={vi.fn()}
        onReanalyze={vi.fn()}
      />,
    );
    const buttons = screen.getAllByRole("button").map((b) => b.textContent);
    expect(buttons[0]).toBe("Analizar de nuevo");
    expect(screen.getByRole("button", { name: "Ver historial" })).toBeInTheDocument();
  });

  it("none applied: 'Analizar de nuevo' is primary, 'Ver historial' secondary", () => {
    render(
      <ApplyResultsScreen
        result={result({ applied: 0, notApplied: 2 })}
        onViewHistory={vi.fn()}
        onDone={vi.fn()}
        onReanalyze={vi.fn()}
      />,
    );
    const buttons = screen.getAllByRole("button").map((b) => b.textContent);
    expect(buttons[0]).toBe("Analizar de nuevo");
  });

  it("partial success with no resolvable reanalyze target: 'Volver a la carpeta' is the fallback primary action", () => {
    render(
      <ApplyResultsScreen
        result={result({ applied: 1, notApplied: 1 })}
        onViewHistory={vi.fn()}
        onDone={vi.fn()}
        onReanalyze={null}
      />,
    );
    const buttons = screen.getAllByRole("button").map((b) => b.textContent);
    expect(buttons[0]).toBe("Volver a la carpeta");
    expect(screen.queryByRole("button", { name: "Analizar de nuevo" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ver historial" })).toBeInTheDocument();
  });

  it("clicking 'Analizar de nuevo' calls onReanalyze, not onDone or onViewHistory", async () => {
    const onReanalyze = vi.fn();
    const onDone = vi.fn();
    const onViewHistory = vi.fn();
    render(
      <ApplyResultsScreen
        result={result({ applied: 1, notApplied: 1 })}
        onViewHistory={onViewHistory}
        onDone={onDone}
        onReanalyze={onReanalyze}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Analizar de nuevo" }));
    expect(onReanalyze).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
    expect(onViewHistory).not.toHaveBeenCalled();
  });

  it("'Ver historial' and 'Volver a la carpeta' always call their own handlers, regardless of state", async () => {
    const onViewHistory = vi.fn();
    const onDone = vi.fn();
    render(
      <ApplyResultsScreen result={result()} onViewHistory={onViewHistory} onDone={onDone} onReanalyze={null} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Ver historial" }));
    await userEvent.click(screen.getByRole("button", { name: "Volver a la carpeta" }));
    expect(onViewHistory).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
