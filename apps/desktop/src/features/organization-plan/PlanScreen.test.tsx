import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { PlanScreen } from "./PlanScreen";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

const ANALYSIS_RESULT = {
  outcome: "ok",
  result: {
    outcome: "ok",
    scanId: "scan-1",
    filesDiscovered: 2,
    protectedTreesMessage: null,
    failures: [],
    items: [
      { fileId: "f1", filename: "invoice.pdf", policyDecisionId: "pd-ready" },
      { fileId: "f2", filename: "photo.jpg", policyDecisionId: "pd-review" },
    ],
  },
};

const PLAN_RESULT = {
  outcome: "ok",
  result: {
    outcome: "ok",
    id: "plan-1",
    managedRootId: "root-1",
    rootDisplayPath: "C:/Descargas",
    structuralProtectionNote: null,
    attentions: [],
    summary: {
      filesTotal: 2,
      ready: 1,
      reviewRequired: 1,
      conflicts: 0,
      invalid: 0,
      blocked: 0,
      skipped: 0,
      noAction: 0,
      protected: 0,
      issues: 0,
    },
    items: [
      {
        actionId: "pd-ready",
        filename: "invoice.pdf",
        sourceDisplayPath: "C:/Descargas/invoice.pdf",
        destinationDisplayPath: "C:/Descargas/Documents/invoice.pdf",
        categoryLabel: "Documento",
        status: "ready",
        title: "Listo para organizar",
        detail: "Este archivo está listo para organizarse.",
        severity: "info",
        selectable: true,
      },
      {
        actionId: "pd-review",
        filename: "photo.jpg",
        sourceDisplayPath: "C:/Descargas/photo.jpg",
        destinationDisplayPath: null,
        categoryLabel: "Imagen",
        status: "review_required",
        title: "Necesita tu revisión",
        detail: "Necesitamos tu aprobación antes de mover este archivo.",
        severity: "attention",
        selectable: false,
      },
    ],
  },
};

function mockInvokeByCommand() {
  vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
    const command = (args as { command?: string })?.command;
    if (command === "analysis.run") return ANALYSIS_RESULT;
    if (command === "plan.create") return PLAN_RESULT;
    if (command === "apply.items") {
      return {
        outcome: "ok",
        result: {
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
        },
      };
    }
    return { outcome: "ok", result: {} };
  });
}

function renderScreen(onApplyCompleted = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PlanScreen
        managedRootId="root-1"
        onApplyCompleted={onApplyCompleted}
        onApplyPendingChange={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return { onApplyCompleted };
}

describe("PlanScreen", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    mockInvokeByCommand();
  });
  afterEach(() => vi.clearAllMocks());

  it("shows a checkbox only for the READY item, and Aprobar/Omitir for the review item", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");

    // The master "Seleccionar todos los listos" checkbox plus exactly one
    // per-item checkbox (the READY item only -- the review item gets
    // Aprobar/Omitir instead).
    expect(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Seleccionar photo.jpg" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aprobar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Omitir" })).toBeInTheDocument();
  });

  it("keeps 'Organizar' disabled until at least one item is selected", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");

    const organizeButton = screen.getByRole("button", { name: "Organizar 0 archivos" });
    expect(organizeButton).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" }));
    expect(screen.getByRole("button", { name: "Organizar 1 archivo" })).not.toBeDisabled();
  });

  it("disables 'Organizar' synchronously on click, so a double-click cannot issue two batches", async () => {
    const onApplyCompleted = vi.fn();
    renderScreen(onApplyCompleted);
    await screen.findByText("invoice.pdf");
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" }));

    const organizeButton = screen.getByRole("button", { name: "Organizar 1 archivo" });
    await userEvent.click(organizeButton);
    // Immediately after the first click completes, the button must
    // already be disabled -- selection was cleared synchronously.
    expect(screen.getByRole("button", { name: "Organizar 0 archivos" })).toBeDisabled();

    await waitFor(() => {
      const applyCalls = vi
        .mocked(invoke)
        .mock.calls.filter(
          ([, args]) => (args as { command?: string })?.command === "apply.items",
        );
      expect(applyCalls).toHaveLength(1);
    });
    await waitFor(() => {
      expect(onApplyCompleted).toHaveBeenCalledWith(
        "root-1",
        expect.objectContaining({ outcome: "ok" }),
      );
    });
  });
});
