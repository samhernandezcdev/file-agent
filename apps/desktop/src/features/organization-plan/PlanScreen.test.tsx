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
        needsReviewAction: false,
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
        needsReviewAction: true,
      },
    ],
  },
};

const PLAN_RESULT_WITH_ATTENTIONS = {
  outcome: "ok",
  result: {
    ...PLAN_RESULT.result,
    attentions: [
      {
        variant: "missing_destination_folder",
        categoryLabel: "Documento",
        destinationLabel: "Documents",
        destinationCategory: "documents",
        message: {
          title: "Falta preparar esta carpeta",
          detail: "1 archivo está listo para clasificarse como Documento, pero falta:\n\nDocuments",
          severity: "attention",
          suggestedAction: "reanalyze",
        },
        affectedFilenames: ["invoice.pdf"],
      },
      {
        variant: "missing_destination_folder",
        categoryLabel: "Imagen",
        destinationLabel: "Images",
        destinationCategory: "images",
        message: {
          title: "Falta preparar esta carpeta",
          detail: "1 archivo está listo para clasificarse como Imagen, pero falta:\n\nImages",
          severity: "attention",
          suggestedAction: "reanalyze",
        },
        affectedFilenames: ["photo.jpg"],
      },
    ],
  },
};

function destinationSetupResult(
  items: { destinationCategory: string; destinationLabel: string; status: string }[],
) {
  return {
    outcome: "ok",
    result: {
      outcome: "ok",
      setupId: "setup-1",
      managedRootId: "root-1",
      items: items.map((item) => ({
        ...item,
        message: {
          title: item.status === "prepared" ? "Preparada" : "Ya estaba disponible",
          detail: item.status === "prepared" ? "FileAgent creó esta carpeta." : "Esta carpeta ya existía.",
          severity: "info",
          suggestedAction: "none",
        },
      })),
      summaryMessage: {
        title: "Los destinos están listos.",
        detail: "FileAgent debe volver a comprobar la carpeta antes de organizar.",
        severity: "info",
        suggestedAction: "reanalyze",
      },
    },
  };
}

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

describe("PlanScreen -- destination setup", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
  });
  afterEach(() => vi.clearAllMocks());

  function mockWithAttentions(prepareResult: unknown) {
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT_WITH_ATTENTIONS;
      if (command === "destination_setup.prepare") return prepareResult;
      return { outcome: "ok", result: {} };
    });
  }

  function renderWithAttentions() {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <PlanScreen
          managedRootId="root-1"
          onApplyCompleted={vi.fn()}
          onApplyPendingChange={vi.fn()}
        />
      </QueryClientProvider>,
    );
  }

  it("shows an aggregate 'Preparar N carpetas' strip with 2+ attentions, requesting exactly those categories", async () => {
    mockWithAttentions(
      destinationSetupResult([
        { destinationCategory: "documents", destinationLabel: "Documents", status: "prepared" },
        { destinationCategory: "images", destinationLabel: "Images", status: "prepared" },
      ]),
    );
    renderWithAttentions();
    await screen.findByText("Faltan 2 carpetas para completar la organización");

    await userEvent.click(screen.getByRole("button", { name: "Preparar 2 carpetas" }));

    await waitFor(() => {
      const call = vi
        .mocked(invoke)
        .mock.calls.find(
          ([, args]) => (args as { command?: string })?.command === "destination_setup.prepare",
        );
      expect(call).toBeDefined();
      const params = (call?.[1] as { params: { destinationCategories: string[] } }).params;
      expect(params.destinationCategories).toEqual(["documents", "images"]);
    });

    expect(await screen.findByText("Documents — Preparada")).toBeInTheDocument();
    expect(await screen.findByText("Images — Preparada")).toBeInTheDocument();
  });

  it("per-panel 'Preparar carpeta' requests exactly that one category, leaving the other attention untouched", async () => {
    mockWithAttentions(
      destinationSetupResult([
        { destinationCategory: "documents", destinationLabel: "Documents", status: "prepared" },
      ]),
    );
    renderWithAttentions();
    const prepareButtons = await screen.findAllByRole("button", { name: "Preparar carpeta" });
    expect(prepareButtons).toHaveLength(2);

    await userEvent.click(prepareButtons[0]);

    await waitFor(() => {
      const call = vi
        .mocked(invoke)
        .mock.calls.find(
          ([, args]) => (args as { command?: string })?.command === "destination_setup.prepare",
        );
      const params = (call?.[1] as { params: { destinationCategories: string[] } }).params;
      expect(params.destinationCategories).toEqual(["documents"]);
    });

    expect(await screen.findByText("Documents — Preparada")).toBeInTheDocument();
    // The Images attention is untouched -- still the original panel, not a result.
    expect(screen.getByRole("button", { name: "Preparar carpeta" })).toBeInTheDocument();
  });

  it("never triggers analysis.run/plan.create again after a prepare result (no automatic reanalysis)", async () => {
    mockWithAttentions(
      destinationSetupResult([
        { destinationCategory: "documents", destinationLabel: "Documents", status: "prepared" },
        { destinationCategory: "images", destinationLabel: "Images", status: "prepared" },
      ]),
    );
    renderWithAttentions();
    await screen.findByText("Faltan 2 carpetas para completar la organización");
    const analysisCallsBefore = vi
      .mocked(invoke)
      .mock.calls.filter(([, args]) => (args as { command?: string })?.command === "analysis.run")
      .length;

    await userEvent.click(screen.getByRole("button", { name: "Preparar 2 carpetas" }));
    await screen.findByText("Documents — Preparada");

    const analysisCallsAfter = vi
      .mocked(invoke)
      .mock.calls.filter(([, args]) => (args as { command?: string })?.command === "analysis.run")
      .length;
    expect(analysisCallsAfter).toBe(analysisCallsBefore);
  });
});
