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

// FA-017.6 Remediation 2: a dedicated 2-selectable-READY-item fixture,
// separate from the shared 1-ready/1-review-required PLAN_RESULT above, so
// the held-pending regression test below can select 2 items and prove the
// submitted count survives independently of `selected` (which clears to 0
// on submit).
const ANALYSIS_RESULT_TWO_READY = {
  outcome: "ok",
  result: {
    ...ANALYSIS_RESULT.result,
    items: [
      { fileId: "f1", filename: "invoice.pdf", policyDecisionId: "pd-ready-1" },
      { fileId: "f2", filename: "receipt.pdf", policyDecisionId: "pd-ready-2" },
    ],
  },
};

const PLAN_RESULT_TWO_READY = {
  outcome: "ok",
  result: {
    ...PLAN_RESULT.result,
    summary: { ...PLAN_RESULT.result.summary, ready: 2, reviewRequired: 0 },
    items: [
      {
        actionId: "pd-ready-1",
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
        actionId: "pd-ready-2",
        filename: "receipt.pdf",
        sourceDisplayPath: "C:/Descargas/receipt.pdf",
        destinationDisplayPath: "C:/Descargas/Documents/receipt.pdf",
        categoryLabel: "Documento",
        status: "ready",
        title: "Listo para organizar",
        detail: "Este archivo está listo para organizarse.",
        severity: "info",
        selectable: true,
        needsReviewAction: false,
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
        onDestinationSetupCompleted={vi.fn()}
        onChooseAnotherFolder={vi.fn()}
        onViewHistory={vi.fn()}
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

  // FA-017.4 Minor 1: "Organizar 0 archivos" must never exist in the DOM
  // -- not rendered, not merely disabled -- while nothing is selected.
  it("does not render 'Organizar' at all until at least one item is selected", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");

    expect(screen.queryByRole("button", { name: /^Organizar/ })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" }));
    expect(screen.getByRole("button", { name: "Organizar 1 archivo" })).not.toBeDisabled();
  });

  it("removes 'Organizar' synchronously on click, so a double-click cannot issue two batches", async () => {
    const onApplyCompleted = vi.fn();
    renderScreen(onApplyCompleted);
    await screen.findByText("invoice.pdf");
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" }));

    const organizeButton = screen.getByRole("button", { name: "Organizar 1 archivo" });
    await userEvent.click(organizeButton);
    // Immediately after the first click completes, the button must
    // already be gone -- selection was cleared synchronously, so a second
    // click physically cannot land on it.
    expect(screen.queryByRole("button", { name: /^Organizar/ })).not.toBeInTheDocument();

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
          onDestinationSetupCompleted={vi.fn()}
          onChooseAnotherFolder={vi.fn()}
          onViewHistory={vi.fn()}
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

  it("also reports the completion to onDestinationSetupCompleted, alongside the existing local result state", async () => {
    const onDestinationSetupCompleted = vi.fn();
    mockWithAttentions(
      destinationSetupResult([
        { destinationCategory: "documents", destinationLabel: "Documents", status: "prepared" },
        { destinationCategory: "images", destinationLabel: "Images", status: "prepared" },
      ]),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <PlanScreen
          managedRootId="root-1"
          onApplyCompleted={vi.fn()}
          onApplyPendingChange={vi.fn()}
          onDestinationSetupCompleted={onDestinationSetupCompleted}
          onChooseAnotherFolder={vi.fn()}
          onViewHistory={vi.fn()}
        />
      </QueryClientProvider>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Preparar 2 carpetas" }));
    await screen.findByText("Documents — Preparada");

    expect(onDestinationSetupCompleted).toHaveBeenCalledTimes(1);
    expect(onDestinationSetupCompleted).toHaveBeenCalledWith(
      "root-1",
      expect.objectContaining({ outcome: "ok" }),
    );
  });

  // FA-017.4 Part 16: distinct busy label for an explicit reanalysis (as
  // opposed to the very first load). Uses the top invalidated-plan
  // banner's own "Analizar de nuevo" -- the only reanalyze affordance
  // that survives the click itself, since handleReanalyze synchronously
  // clears the per-category destinationResults state that the
  // ConflictSummary result banners (and their own "Analizar de nuevo")
  // depend on, reverting those panels to "Preparar carpeta" immediately
  // (pre-existing, unchanged behavior -- not something this ticket
  // touches).
  it("shows 'Analizando de nuevo…' and disables the banner's reanalyze button while an explicit reanalysis is in flight", async () => {
    let resolveSecondAnalysis!: (value: unknown) => void;
    const secondAnalysisPromise = new Promise((resolve) => {
      resolveSecondAnalysis = resolve;
    });
    let analysisCallCount = 0;
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") {
        analysisCallCount += 1;
        return analysisCallCount === 1 ? ANALYSIS_RESULT : secondAnalysisPromise;
      }
      if (command === "plan.create") return PLAN_RESULT_WITH_ATTENTIONS;
      if (command === "destination_setup.prepare") {
        return destinationSetupResult([
          { destinationCategory: "documents", destinationLabel: "Documents", status: "prepared" },
          { destinationCategory: "images", destinationLabel: "Images", status: "prepared" },
        ]);
      }
      return { outcome: "ok", result: {} };
    });
    renderWithAttentions();
    await userEvent.click(await screen.findByRole("button", { name: "Preparar 2 carpetas" }));
    await screen.findByText("Las carpetas están listas.");

    // Multiple "Analizar de nuevo" buttons exist right after prepare
    // completes (the top invalidated-plan banner plus each per-category
    // ConflictSummary result banner) -- the banner's own button renders
    // first in DOM order.
    const reanalyzeButton = screen.getAllByRole("button", { name: "Analizar de nuevo" })[0];
    await userEvent.click(reanalyzeButton);

    const busyButton = await screen.findByRole("button", { name: "Analizando de nuevo…" });
    expect(busyButton).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Analizar de nuevo" })).not.toBeInTheDocument();

    resolveSecondAnalysis(ANALYSIS_RESULT);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Analizando de nuevo…" })).not.toBeInTheDocument(),
    );
  });
});

const PLAN_RESULT_ALL_REVIEW_REQUIRED = {
  outcome: "ok",
  result: {
    ...PLAN_RESULT.result,
    attentions: [],
    summary: { ...PLAN_RESULT.result.summary, ready: 0, reviewRequired: 2 },
    items: [
      {
        actionId: "pd-review-1",
        filename: "a.jpg",
        sourceDisplayPath: "C:/Descargas/a.jpg",
        destinationDisplayPath: null,
        categoryLabel: "Imagen",
        status: "review_required",
        title: "Necesita tu revisión",
        detail: "Necesitamos tu aprobación antes de mover este archivo.",
        severity: "attention",
        selectable: false,
        needsReviewAction: true,
      },
      {
        actionId: "pd-review-2",
        filename: "b.jpg",
        sourceDisplayPath: "C:/Descargas/b.jpg",
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

const PLAN_RESULT_NOTHING_ACTIONABLE = {
  outcome: "ok",
  result: {
    ...PLAN_RESULT.result,
    attentions: [],
    summary: { ...PLAN_RESULT.result.summary, ready: 0, reviewRequired: 0, skipped: 1 },
    items: [
      {
        actionId: "pd-skip-1",
        filename: "old.tmp",
        sourceDisplayPath: "C:/Descargas/old.tmp",
        destinationDisplayPath: null,
        categoryLabel: "Otro",
        status: "skipped",
        title: "Ya estaba organizado",
        detail: "No requiere ninguna acción.",
        severity: "info",
        selectable: false,
        needsReviewAction: false,
      },
    ],
  },
};

describe("PlanScreen -- CTA hierarchy (FA-017.4)", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    mockInvokeByCommand();
  });
  afterEach(() => vi.clearAllMocks());

  it("promotes 'Seleccionar todos los listos' with a prominent container while nothing is selected", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");

    const selectAllCheckbox = screen.getByRole("checkbox", { name: "Seleccionar todos los listos" });
    expect(selectAllCheckbox.closest("div")?.className).toContain("border-info");
    expect(screen.queryByRole("button", { name: /^Organizar/ })).not.toBeInTheDocument();
  });

  it("demotes 'Seleccionar todos los listos' once an item is selected, and 'Organizar' becomes primary", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" }));

    const selectAllCheckbox = screen.getByRole("checkbox", { name: "Seleccionar todos los listos" });
    expect(selectAllCheckbox.closest("div")?.className).not.toContain("border-info");
    expect(screen.getByRole("button", { name: "Organizar 1 archivo" })).toBeInTheDocument();
  });

  it("shows orienting copy (no bulk action) when only review-required items remain", async () => {
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT_ALL_REVIEW_REQUIRED;
      return { outcome: "ok", result: {} };
    });
    renderScreen();
    await screen.findByText("a.jpg");

    expect(
      screen.getByText("Revisa cada archivo para continuar: aprueba o omite antes de organizar."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Seleccionar todos los listos" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Organizar/ })).not.toBeInTheDocument();
  });

  it("renders NOTHING_ACTIONABLE with 'Elegir otra carpeta' when nothing requires action, never 'Organizar 0 archivos'", async () => {
    const onChooseAnotherFolder = vi.fn();
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT_NOTHING_ACTIONABLE;
      return { outcome: "ok", result: {} };
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <PlanScreen
          managedRootId="root-1"
          onApplyCompleted={vi.fn()}
          onApplyPendingChange={vi.fn()}
          onDestinationSetupCompleted={vi.fn()}
          onChooseAnotherFolder={onChooseAnotherFolder}
          onViewHistory={vi.fn()}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("No hay nada que organizar en este momento.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Organizar/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/^Organizar 0 archivos/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Elegir otra carpeta" }));
    expect(onChooseAnotherFolder).toHaveBeenCalledTimes(1);
  });

  it("offers 'Ver historial' on the in-place apply guidance only for unknown_mutation_outcome", async () => {
    const onViewHistory = vi.fn();
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT;
      if (command === "apply.items") return { outcome: "unknown_mutation_outcome" };
      return { outcome: "ok", result: {} };
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <PlanScreen
          managedRootId="root-1"
          onApplyCompleted={vi.fn()}
          onApplyPendingChange={vi.fn()}
          onDestinationSetupCompleted={vi.fn()}
          onChooseAnotherFolder={vi.fn()}
          onViewHistory={onViewHistory}
        />
      </QueryClientProvider>,
    );

    await screen.findByText("invoice.pdf");
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Organizar 1 archivo" }));

    const historyButton = await screen.findByRole("button", { name: "Ver historial" });
    await userEvent.click(historyButton);
    expect(onViewHistory).toHaveBeenCalledTimes(1);
  });
});

describe("PlanScreen -- compact context bar / sticky footer (FA-017.6)", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    mockInvokeByCommand();
  });
  afterEach(() => vi.clearAllMocks());

  it("shows the compact context bar with root name and READY count once the plan resolves", async () => {
    renderScreen();
    expect(await screen.findByText("C:/Descargas · 1 listo")).toBeInTheDocument();
  });

  it("compact context bar includes attention count when attentions exist (MIXED)", async () => {
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT_WITH_ATTENTIONS;
      return { outcome: "ok", result: {} };
    });
    renderScreen();
    expect(
      await screen.findByText("C:/Descargas · 1 listo · 2 necesitan atención"),
    ).toBeInTheDocument();
  });

  it("compact context bar renders exactly once", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");
    expect(screen.getAllByText(/· \d+ listo/)).toHaveLength(1);
  });

  it("compact context bar element appears after the select-all row and before the file list in DOM order", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");
    const contextBar = screen.getByText("C:/Descargas · 1 listo");
    const selectAll = screen.getByRole("checkbox", { name: "Seleccionar todos los listos" });
    const fileList = screen.getByLabelText("Archivos analizados");
    // DOM order: selectAll before contextBar before fileList.
    expect(
      selectAll.compareDocumentPosition(contextBar.parentElement as Node) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      (contextBar.parentElement as Node).compareDocumentPosition(fileList) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("compact context bar carries the sticky top-0 classes", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");
    const bar = screen.getByText("C:/Descargas · 1 listo").parentElement as HTMLElement;
    expect(bar.className).toContain("sticky");
    expect(bar.className).toContain("top-0");
  });

  it("does not render the context bar before plan facts exist (initial loading)", async () => {
    let resolvePlan!: (value: unknown) => void;
    const planPromise = new Promise((resolve) => {
      resolvePlan = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return planPromise;
      return { outcome: "ok", result: {} };
    });
    renderScreen();
    await screen.findByText(/archivos encontrados/);
    expect(screen.queryByText(/· \d+ listo/)).not.toBeInTheDocument();
    resolvePlan(PLAN_RESULT);
    expect(await screen.findByText("C:/Descargas · 1 listo")).toBeInTheDocument();
  });

  it("selected === 0: no sticky footer, no Organize button anywhere", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");
    expect(screen.queryByRole("button", { name: /^Organizar/ })).not.toBeInTheDocument();
  });

  it("selected > 0: exactly one Organizar control exists, inside the sticky footer, with compact copy", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" }));

    const buttons = screen.getAllByRole("button", { name: /^Organizar/ });
    expect(buttons).toHaveLength(1);
    expect(screen.getByText("1 seleccionado · 0 se eliminarán")).toBeInTheDocument();
    // The full, non-sticky safety sentence is also present, text-only.
    expect(
      screen.getByText(/1 archivo se moverá · 0 archivos se eliminarán · Puedes deshacer los cambios/),
    ).toBeInTheDocument();

    const footer = buttons[0].closest("div");
    expect(footer?.className).toContain("sticky");
    expect(footer?.className).toContain("bottom-0");
  });

  // FA-017.6 Remediation 2 -- THE PRECISE BUG: a held (never synchronously
  // resolved) apply.items promise is required here -- if the mock resolved
  // immediately, `applyItems.isPending` could already be false by the time
  // of these assertions, and the test would pass whether or not the footer
  // regression existed. This is the regression test the adversarial review
  // asked for, extended to 2 selected READY items to prove the pending
  // count comes from the submitted request, not from `selected`.
  it("held-pending apply.items: sticky footer stays mounted, shows the submitted count, disabled 'Organizando…', exactly one control -- then resolves normally", async () => {
    let resolveApply!: (value: unknown) => void;
    const applyPromise = new Promise((resolve) => {
      resolveApply = resolve;
    });
    let applyCallArgs: unknown;
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") return ANALYSIS_RESULT_TWO_READY;
      if (command === "plan.create") return PLAN_RESULT_TWO_READY;
      if (command === "apply.items") {
        applyCallArgs = args;
        return applyPromise;
      }
      return { outcome: "ok", result: {} };
    });
    const onApplyCompleted = vi.fn();
    renderScreen(onApplyCompleted);
    await screen.findByText("invoice.pdf");
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar receipt.pdf" }));

    await userEvent.click(screen.getByRole("button", { name: "Organizar 2 archivos" }));

    // Selection is no longer authorized for resubmission: `selected`
    // cleared synchronously on submit -- both checkboxes are back to
    // unchecked (unchanged double-submit safety) -- yet the sticky footer
    // is still mounted.
    expect(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByRole("checkbox", { name: "Seleccionar receipt.pdf" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    const pendingButtons = screen.getAllByRole("button", { name: "Organizando…" });
    expect(pendingButtons).toHaveLength(1);
    expect(pendingButtons[0]).toBeDisabled();
    expect(screen.getByText("2 seleccionados · 0 se eliminarán")).toBeInTheDocument();
    // Never two controls for the one action -- no stale "Organizar N
    // archivos" button coexists with the busy one.
    expect(screen.queryByRole("button", { name: /^Organizar \d/ })).not.toBeInTheDocument();

    // The mutation received exactly the 2 ids that were selected pre-submit.
    expect(
      (applyCallArgs as { params: { policyDecisionIds: string[] } }).params.policyDecisionIds,
    ).toEqual(["pd-ready-1", "pd-ready-2"]);

    resolveApply({
      outcome: "ok",
      result: {
        outcome: "ok",
        batchId: "batch-1",
        status: "completed",
        startedAt: "2026-01-01T00:00:00Z",
        completedAt: "2026-01-01T00:00:01Z",
        managedRootId: "root-1",
        items: [],
        summary: { selected: 2, processed: 2, applied: 2, notApplied: 0, skipped: 0, invalid: 0 },
        summaryMessage: {
          title: "2 archivos se organizaron correctamente.",
          detail: "Todos los archivos seleccionados se movieron a su carpeta.",
          severity: "info",
          suggestedAction: "none",
        },
      },
    });

    // Terminal known success: existing result/navigation handoff fires
    // exactly as before this remediation, and the footer does not linger.
    await waitFor(() => {
      expect(onApplyCompleted).toHaveBeenCalledWith(
        "root-1",
        expect.objectContaining({ outcome: "ok" }),
      );
    });
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /^Organiz/ })).not.toBeInTheDocument();
    });
    // No selection is ever restored after a pending apply settles.
    expect(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("selected > 0, idle (not pending): footer visible with exactly one 'Organizar N archivo(s)' button", async () => {
    renderScreen();
    await screen.findByText("invoice.pdf");
    expect(screen.queryByRole("button", { name: /^Organiz/ })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoice.pdf" }));

    expect(screen.getAllByRole("button", { name: "Organizar 1 archivo" })).toHaveLength(1);
  });

  it("PLAN_STALE: no sticky Organize footer, no numeric counts in the context bar", async () => {
    let analysisCallCount = 0;
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") {
        analysisCallCount += 1;
        return ANALYSIS_RESULT;
      }
      if (command === "plan.create") return PLAN_RESULT_WITH_ATTENTIONS;
      if (command === "destination_setup.prepare") {
        return destinationSetupResult([
          { destinationCategory: "documents", destinationLabel: "Documents", status: "prepared" },
          { destinationCategory: "images", destinationLabel: "Images", status: "prepared" },
        ]);
      }
      return { outcome: "ok", result: {} };
    });
    renderScreen();
    await userEvent.click(await screen.findByRole("button", { name: "Preparar 2 carpetas" }));
    await screen.findByText("Las carpetas están listas.");

    expect(screen.getByText("Analiza de nuevo para actualizar esta vista")).toBeInTheDocument();
    expect(screen.queryByText(/· \d+ listo/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Organizar/ })).not.toBeInTheDocument();
    expect(analysisCallCount).toBe(1);
  });

  it("reanalyzing: context bar shows the busy label, no numeric counts", async () => {
    let resolveSecondAnalysis!: (value: unknown) => void;
    const secondAnalysisPromise = new Promise((resolve) => {
      resolveSecondAnalysis = resolve;
    });
    let analysisCallCount = 0;
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") {
        analysisCallCount += 1;
        return analysisCallCount === 1 ? ANALYSIS_RESULT : secondAnalysisPromise;
      }
      if (command === "plan.create") return PLAN_RESULT_WITH_ATTENTIONS;
      if (command === "destination_setup.prepare") {
        return destinationSetupResult([
          { destinationCategory: "documents", destinationLabel: "Documents", status: "prepared" },
          { destinationCategory: "images", destinationLabel: "Images", status: "prepared" },
        ]);
      }
      return { outcome: "ok", result: {} };
    });
    renderScreen();
    await userEvent.click(await screen.findByRole("button", { name: "Preparar 2 carpetas" }));
    await screen.findByText("Las carpetas están listas.");
    const reanalyzeButtons = screen.getAllByRole("button", { name: "Analizar de nuevo" });
    await userEvent.click(reanalyzeButtons[0]);

    expect(await screen.findByText("Analizando de nuevo…")).toBeInTheDocument();
    expect(screen.queryByText(/· \d+ listo/)).not.toBeInTheDocument();

    resolveSecondAnalysis(ANALYSIS_RESULT);
  });

  it("NOTHING_ACTIONABLE: no context bar and no sticky footer (early-return EmptyState)", async () => {
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") {
        return {
          outcome: "ok",
          result: {
            ...PLAN_RESULT.result,
            attentions: [],
            summary: { ...PLAN_RESULT.result.summary, ready: 0, reviewRequired: 0 },
            items: [
              {
                actionId: "pd-skip-1",
                filename: "old.tmp",
                sourceDisplayPath: "C:/Descargas/old.tmp",
                destinationDisplayPath: null,
                categoryLabel: "Otro",
                status: "skipped",
                title: "Ya estaba organizado",
                detail: "No requiere ninguna acción.",
                severity: "info",
                selectable: false,
                needsReviewAction: false,
              },
            ],
          },
        };
      }
      return { outcome: "ok", result: {} };
    });
    renderScreen();
    expect(await screen.findByText("No hay nada que organizar en este momento.")).toBeInTheDocument();
    expect(screen.queryByText(/· \d+ listo/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Organizar/ })).not.toBeInTheDocument();
  });
});
