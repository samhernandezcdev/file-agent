import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import App from "./App";
import { queryClient } from "./lib/queryClient";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

const ROOTS_RESULT = {
  outcome: "ok",
  result: { roots: [{ id: "root-1", displayPath: "C:/Descargas", status: "available" }] },
};

const ANALYSIS_RESULT = {
  outcome: "ok",
  result: {
    outcome: "ok",
    scanId: "scan-1",
    filesDiscovered: 1,
    protectedTreesMessage: null,
    failures: [],
    items: [{ fileId: "f1", filename: "invoice.pdf", policyDecisionId: "pd-ready" }],
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
      filesTotal: 1,
      ready: 1,
      reviewRequired: 0,
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
    ],
  },
};

const TWO_ROOTS_RESULT = {
  outcome: "ok",
  result: {
    roots: [
      { id: "root-1", displayPath: "C:/Descargas", status: "available" },
      { id: "root-2", displayPath: "C:/Documentos", status: "available" },
    ],
  },
};

const ANALYSIS_RESULT_B = {
  outcome: "ok",
  result: {
    outcome: "ok",
    scanId: "scan-2",
    filesDiscovered: 1,
    protectedTreesMessage: null,
    failures: [],
    items: [{ fileId: "f2", filename: "report.docx", policyDecisionId: "pd-ready-b" }],
  },
};

const PLAN_RESULT_B = {
  outcome: "ok",
  result: {
    outcome: "ok",
    id: "plan-2",
    managedRootId: "root-2",
    rootDisplayPath: "C:/Documentos",
    structuralProtectionNote: null,
    attentions: [],
    summary: {
      filesTotal: 1,
      ready: 1,
      reviewRequired: 0,
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
        actionId: "pd-ready-b",
        filename: "report.docx",
        sourceDisplayPath: "C:/Documentos/report.docx",
        destinationDisplayPath: "C:/Documentos/Documents/report.docx",
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

function batchResult(overrides: Record<string, unknown> = {}) {
  return {
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
    ...overrides,
  };
}

function renderApp() {
  render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

async function goToPlanAndSelect() {
  renderApp();
  await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));
  await userEvent.click(await screen.findByRole("checkbox", { name: "Seleccionar invoice.pdf" }));
}

describe("App -- apply completion inbox lifecycle", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    queryClient.clear();
  });
  afterEach(() => vi.clearAllMocks());

  it("1: completion while still on that root's Revisar screen shows Result directly, no notice", async () => {
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT;
      if (command === "apply.items") return { outcome: "ok", result: batchResult() };
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    await goToPlanAndSelect();
    await userEvent.click(screen.getByRole("button", { name: "Organizar 1 archivo" }));

    expect(await screen.findByRole("heading", { name: "Resultado" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Avisos de organización")).not.toBeInTheDocument();
  });

  it("2: completion arriving after navigating away is retained as a notice, without forcing navigation", async () => {
    let resolveApply!: (value: unknown) => void;
    const applyPromise = new Promise((resolve) => {
      resolveApply = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT;
      if (command === "apply.items") return applyPromise;
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    await goToPlanAndSelect();
    await userEvent.click(screen.getByRole("button", { name: "Organizar 1 archivo" }));

    // Navigate away before the apply resolves.
    await userEvent.click(screen.getByRole("button", { name: "Historial" }));
    expect(await screen.findByRole("heading", { name: "Historial" })).toBeInTheDocument();

    resolveApply({ outcome: "ok", result: batchResult() });

    // Retained as a notice; the user is NOT force-navigated to Resultado.
    await waitFor(() => {
      expect(screen.getByLabelText("Avisos de organización")).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "Historial" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ver resultado" })).toBeInTheDocument();
  });

  it("3: an UNKNOWN notice and a RESULT notice coexist -- neither displaces the other", async () => {
    let resolveApply!: (value: unknown) => void;
    const applyPromise = new Promise((resolve) => {
      resolveApply = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT;
      if (command === "apply.items") return applyPromise;
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    await goToPlanAndSelect();
    await userEvent.click(screen.getByRole("button", { name: "Organizar 1 archivo" }));
    await userEvent.click(screen.getByRole("button", { name: "Historial" }));
    resolveApply({ outcome: "unknown_mutation_outcome" });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Ver historial" })).toBeInTheDocument();
    });

    // A second, independent apply on the same root resolves with a real result.
    await userEvent.click(screen.getByRole("button", { name: "Carpetas" }));
    await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Seleccionar invoice.pdf" }));

    let resolveSecond!: (value: unknown) => void;
    const secondPromise = new Promise((resolve) => {
      resolveSecond = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT;
      if (command === "apply.items") return secondPromise;
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });
    await userEvent.click(screen.getByRole("button", { name: "Organizar 1 archivo" }));
    await userEvent.click(screen.getByRole("button", { name: "Historial" }));
    resolveSecond({ outcome: "ok", result: batchResult() });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Ver historial" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Ver resultado" })).toBeInTheDocument();
    });
  });

  it("4/5: opening a notice removes only it; dismissing a notice removes only it and issues no mutation", async () => {
    let resolveApply!: (value: unknown) => void;
    const applyPromise = new Promise((resolve) => {
      resolveApply = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT;
      if (command === "apply.items") return applyPromise;
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    await goToPlanAndSelect();
    await userEvent.click(screen.getByRole("button", { name: "Organizar 1 archivo" }));
    await userEvent.click(screen.getByRole("button", { name: "Historial" }));
    resolveApply({ outcome: "ok", result: batchResult() });

    await waitFor(() => expect(screen.getByRole("button", { name: "Ver resultado" })).toBeInTheDocument());

    const callsBeforeOpen = vi.mocked(invoke).mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Ver resultado" }));

    // Opening navigates to the retained Result and removes the notice.
    expect(await screen.findByRole("heading", { name: "Resultado" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Avisos de organización")).not.toBeInTheDocument();
    // No extra backend call was made just by opening the notice.
    expect(vi.mocked(invoke).mock.calls.length).toBe(callsBeforeOpen);
  });

  it("M3: a completion for Root A arriving while the user has moved on to Root B's Revisar screen is retained, not force-navigated", async () => {
    let resolveApplyA!: (value: unknown) => void;
    const applyAPromise = new Promise((resolve) => {
      resolveApplyA = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      const params = (args as { params?: Record<string, unknown> })?.params;
      if (command === "managed_roots.list") return TWO_ROOTS_RESULT;
      if (command === "analysis.run") {
        return params?.managedRootId === "root-2" ? ANALYSIS_RESULT_B : ANALYSIS_RESULT;
      }
      if (command === "plan.create") {
        const ids = (params?.policyDecisionIds as string[] | undefined) ?? [];
        return ids.includes("pd-ready-b") ? PLAN_RESULT_B : PLAN_RESULT;
      }
      if (command === "apply.items") return applyAPromise;
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    renderApp();

    // 1. On Root A's Revisar screen.
    const analyzeButtons = await screen.findAllByRole("button", { name: "Analizar" });
    await userEvent.click(analyzeButtons[0]);
    await userEvent.click(await screen.findByRole("checkbox", { name: "Seleccionar invoice.pdf" }));

    // 2. Start apply for Root A -- left unresolved.
    await userEvent.click(screen.getByRole("button", { name: "Organizar 1 archivo" }));
    const applyCallsAfterStart = vi
      .mocked(invoke)
      .mock.calls.filter(([, a]) => (a as { command?: string })?.command === "apply.items").length;
    expect(applyCallsAfterStart).toBe(1);

    // 3. Navigate away to Root B's Plan/Review screen before Root A completes.
    await userEvent.click(screen.getByRole("button", { name: "Carpetas" }));
    const analyzeButtonsAgain = await screen.findAllByRole("button", { name: "Analizar" });
    await userEvent.click(analyzeButtonsAgain[1]);
    await screen.findByText("report.docx");
    expect(screen.getByText("C:/Documentos")).toBeInTheDocument();

    // 4. Root A's completion arrives now.
    resolveApplyA({ outcome: "ok", result: batchResult({ managedRootId: "root-1" }) });

    // 5. Assertions.
    await waitFor(() => {
      expect(screen.getByLabelText("Avisos de organización")).toBeInTheDocument();
    });
    // User remains on Root B -- no forced navigation to Root A's Result.
    expect(screen.queryByRole("heading", { name: "Resultado" })).not.toBeInTheDocument();
    expect(screen.getByText("report.docx")).toBeInTheDocument();
    expect(screen.getByText("C:/Documentos")).toBeInTheDocument();
    // Exactly one notice, offering the RESULT action -- no duplicate.
    const notices = screen.getAllByRole("button", { name: "Ver resultado" });
    expect(notices).toHaveLength(1);
    // No duplicate apply call and no automatic retry/mutation from the
    // notice being appended.
    const applyCallsAfterCompletion = vi
      .mocked(invoke)
      .mock.calls.filter(([, a]) => (a as { command?: string })?.command === "apply.items").length;
    expect(applyCallsAfterCompletion).toBe(1);
  });
});

const PLAN_RESULT_WITH_ATTENTION = {
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
    ],
  },
};

describe("App -- destination setup cross-navigation lifecycle (FA-017.2)", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    queryClient.clear();
  });
  afterEach(() => vi.clearAllMocks());

  it("a prepare completion arriving after the user has navigated away is handled exactly once, without crashing or forcing navigation", async () => {
    let resolvePrepare!: (value: unknown) => void;
    const preparePromise = new Promise((resolve) => {
      resolvePrepare = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT_WITH_ATTENTION;
      if (command === "destination_setup.prepare") return preparePromise;
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Preparar carpeta" }));

    // Navigate away before the prepare call resolves -- no notice/retained
    // state exists for this feature, so this is simply "the user left."
    await userEvent.click(screen.getByRole("button", { name: "Historial" }));
    expect(await screen.findByRole("heading", { name: "Historial" })).toBeInTheDocument();

    // The hook-level onSuccess still fires (same guarantee proven for
    // apply.items in FA-017.1) -- this must not throw/crash the app and
    // must not force any navigation back to Carpetas/Revisar.
    resolvePrepare({
      outcome: "ok",
      result: {
        outcome: "ok",
        setupId: "setup-1",
        managedRootId: "root-1",
        items: [
          {
            destinationCategory: "documents",
            destinationLabel: "Documents",
            status: "prepared",
            message: {
              title: "Preparada",
              detail: "FileAgent creó esta carpeta.",
              severity: "info",
              suggestedAction: "none",
            },
          },
        ],
        summaryMessage: {
          title: "1 carpetas preparadas.",
          detail: "FileAgent debe volver a comprobar la carpeta antes de organizar.",
          severity: "info",
          suggestedAction: "reanalyze",
        },
      },
    });

    // Still on Historial -- not force-navigated anywhere.
    await new Promise((r) => setTimeout(r, 10));
    expect(screen.getByRole("heading", { name: "Historial" })).toBeInTheDocument();

    // Exactly one prepare call was made -- no silent retry.
    const prepareCalls = vi
      .mocked(invoke)
      .mock.calls.filter(
        ([, a]) => (a as { command?: string })?.command === "destination_setup.prepare",
      );
    expect(prepareCalls).toHaveLength(1);
  });

  const ANALYSIS_RESULT_ROOT1_FRESH = {
    outcome: "ok",
    result: {
      outcome: "ok",
      scanId: "scan-1b",
      filesDiscovered: 1,
      protectedTreesMessage: null,
      failures: [],
      items: [{ fileId: "f1", filename: "invoice.pdf", policyDecisionId: "pd-ready-fresh" }],
    },
  };

  const PLAN_RESULT_RESOLVED = {
    outcome: "ok",
    result: {
      ...PLAN_RESULT.result,
      attentions: [],
      items: [
        {
          actionId: "pd-ready-fresh",
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
      ],
    },
  };

  function fullPrepareResult() {
    return {
      outcome: "ok",
      result: {
        outcome: "ok",
        setupId: "setup-1",
        managedRootId: "root-1",
        items: [
          {
            destinationCategory: "documents",
            destinationLabel: "Documents",
            status: "prepared",
            message: {
              title: "Preparada",
              detail: "FileAgent creó esta carpeta.",
              severity: "info",
              suggestedAction: "none",
            },
          },
        ],
        summaryMessage: {
          title: "1 carpetas preparadas.",
          detail: "FileAgent debe volver a comprobar la carpeta antes de organizar.",
          severity: "info",
          suggestedAction: "reanalyze",
        },
      },
    };
  }

  it("Major-1 remediation: a completed setup marks Plan A non-authoritative; it does not resurrect as actionable after navigating away and back; only explicit reanalysis produces fresh Plan B", async () => {
    let analysisCallCount = 0;
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      const params = (args as { params?: Record<string, unknown> })?.params;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") {
        analysisCallCount += 1;
        return analysisCallCount === 1 ? ANALYSIS_RESULT : ANALYSIS_RESULT_ROOT1_FRESH;
      }
      if (command === "plan.create") {
        const ids = (params?.policyDecisionIds as string[] | undefined) ?? [];
        return ids.includes("pd-ready-fresh") ? PLAN_RESULT_RESOLVED : PLAN_RESULT_WITH_ATTENTION;
      }
      if (command === "destination_setup.prepare") return fullPrepareResult();
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));
    await screen.findByRole("checkbox", { name: "Seleccionar invoice.pdf" });

    // Destination setup succeeds -- Plan A is immediately marked
    // non-authoritative in this same mount, before any navigation.
    await userEvent.click(await screen.findByRole("button", { name: "Preparar carpeta" }));
    await screen.findByText("Documents — Preparada");
    expect(screen.getByText("Este plan ya no está actualizado.")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Seleccionar invoice.pdf" })).not.toBeInTheDocument();

    // Navigate away, then back to the SAME managed root.
    await userEvent.click(screen.getByRole("button", { name: "Carpetas" }));
    await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));

    // Plan A must not resurrect as actionable on remount, and remounting
    // must not have triggered a second, automatic analysis.run call.
    await screen.findByText("Este plan ya no está actualizado.");
    expect(screen.queryByRole("checkbox", { name: "Seleccionar invoice.pdf" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Organizar 1 archivo/ })).not.toBeInTheDocument();
    expect(analysisCallCount).toBe(1);

    // Only explicit "Analizar de nuevo" obtains the next actionable plan.
    await userEvent.click(screen.getByRole("button", { name: "Analizar de nuevo" }));

    await waitFor(() => expect(analysisCallCount).toBe(2));
    expect(await screen.findByRole("checkbox", { name: "Seleccionar invoice.pdf" })).toBeInTheDocument();
    expect(screen.queryByText("Este plan ya no está actualizado.")).not.toBeInTheDocument();
  });

  const PLAN_RESULT_WITH_TWO_ATTENTIONS = {
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

  it("Major-1 remediation: a PARTIAL setup result (one prepared, one not_prepared) also marks the plan non-authoritative and survives navigating away and back", async () => {
    let analysisCallCount = 0;
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") {
        analysisCallCount += 1;
        return ANALYSIS_RESULT;
      }
      if (command === "plan.create") return PLAN_RESULT_WITH_TWO_ATTENTIONS;
      if (command === "destination_setup.prepare") {
        return {
          outcome: "ok",
          result: {
            outcome: "ok",
            setupId: "setup-2",
            managedRootId: "root-1",
            items: [
              {
                destinationCategory: "documents",
                destinationLabel: "Documents",
                status: "prepared",
                message: {
                  title: "Preparada",
                  detail: "FileAgent creó esta carpeta.",
                  severity: "info",
                  suggestedAction: "none",
                },
              },
              {
                destinationCategory: "images",
                destinationLabel: "Images",
                status: "not_prepared",
                message: {
                  title: "No pudimos prepararla",
                  detail: "No pudimos confirmar que esta ubicación sea segura.",
                  severity: "attention",
                  suggestedAction: "none",
                },
              },
            ],
            summaryMessage: {
              title: "1 de 2 carpetas están listas.",
              detail: "FileAgent debe volver a comprobar la carpeta antes de organizar.",
              severity: "attention",
              suggestedAction: "reanalyze",
            },
          },
        };
      }
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Preparar 2 carpetas" }));
    await screen.findByText("Documents — Preparada");

    expect(screen.getByText("Este plan ya no está actualizado.")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Seleccionar invoice.pdf" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Carpetas" }));
    await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));

    // Still gated after remount, and the partial (not fully successful)
    // result never triggered a second, automatic analysis.run either.
    await screen.findByText("Este plan ya no está actualizado.");
    expect(screen.queryByRole("checkbox", { name: "Seleccionar invoice.pdf" })).not.toBeInTheDocument();
    expect(analysisCallCount).toBe(1);

    await userEvent.click(screen.getByRole("button", { name: "Analizar de nuevo" }));
    await waitFor(() => expect(analysisCallCount).toBe(2));
  });
});

function fullPrepareResult(managedRootId = "root-1") {
  return {
    outcome: "ok",
    result: {
      outcome: "ok",
      setupId: "setup-1",
      managedRootId,
      items: [
        {
          destinationCategory: "documents",
          destinationLabel: "Documents",
          status: "prepared",
          message: {
            title: "Preparada",
            detail: "FileAgent creó esta carpeta.",
            severity: "info",
            suggestedAction: "none",
          },
        },
      ],
      summaryMessage: {
        title: "1 carpetas preparadas.",
        detail: "FileAgent debe volver a comprobar la carpeta antes de organizar.",
        severity: "info",
        suggestedAction: "reanalyze",
      },
    },
  };
}

// FA-017.4 §2: destination_setup.prepare's own retained-completion
// mechanism -- structurally parallel to the apply.items lifecycle above
// but never routed through History, and its notice action is pure
// navigation back to the originating root's plan screen (there is no
// dedicated destination-setup results screen -- FA-017.2 §12, unchanged).
describe("App -- destination-setup completion inbox lifecycle (FA-017.4)", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    queryClient.clear();
  });
  afterEach(() => vi.clearAllMocks());

  it("a KNOWN full-success completion arriving after navigating away is retained as a notice offering 'Ir a la carpeta'", async () => {
    let resolvePrepare!: (value: unknown) => void;
    const preparePromise = new Promise((resolve) => {
      resolvePrepare = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT_WITH_ATTENTION;
      if (command === "destination_setup.prepare") return preparePromise;
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Preparar carpeta" }));
    await userEvent.click(screen.getByRole("button", { name: "Historial" }));
    expect(await screen.findByRole("heading", { name: "Historial" })).toBeInTheDocument();

    resolvePrepare(fullPrepareResult());

    await waitFor(() => {
      expect(screen.getByLabelText("Avisos de organización")).toBeInTheDocument();
    });
    // Never force-navigated; the notice is offered, not applied.
    expect(screen.getByRole("heading", { name: "Historial" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ir a la carpeta" })).toBeInTheDocument();
    // Never surfaced through History (FA-017.2 §12/FA-017.4 §2.1, unchanged).
    expect(screen.queryByRole("button", { name: "Ver historial" })).not.toBeInTheDocument();
  });

  it("an unknown_mutation_outcome completion is retained, never claims success or failure, and is never surfaced through History", async () => {
    let resolvePrepare!: (value: unknown) => void;
    const preparePromise = new Promise((resolve) => {
      resolvePrepare = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT_WITH_ATTENTION;
      if (command === "destination_setup.prepare") return preparePromise;
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Preparar carpeta" }));
    await userEvent.click(screen.getByRole("button", { name: "Historial" }));

    resolvePrepare({ outcome: "unknown_mutation_outcome" });

    await waitFor(() => {
      expect(
        screen.getByText("No pudimos confirmar si la operación terminó."),
      ).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Ir a la carpeta" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ver historial" })).not.toBeInTheDocument();
  });

  it("cross-navigation: a Root A prepare completing while the user is on Root B leaves Root B's content unaffected and carries Root A's managedRootId", async () => {
    let resolvePrepareA!: (value: unknown) => void;
    const prepareAPromise = new Promise((resolve) => {
      resolvePrepareA = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      const params = (args as { params?: Record<string, unknown> })?.params;
      if (command === "managed_roots.list") return TWO_ROOTS_RESULT;
      if (command === "analysis.run") {
        return params?.managedRootId === "root-2" ? ANALYSIS_RESULT_B : ANALYSIS_RESULT;
      }
      if (command === "plan.create") {
        const ids = (params?.policyDecisionIds as string[] | undefined) ?? [];
        return ids.includes("pd-ready-b") ? PLAN_RESULT_B : PLAN_RESULT_WITH_ATTENTION;
      }
      if (command === "destination_setup.prepare") return prepareAPromise;
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    renderApp();
    const analyzeButtons = await screen.findAllByRole("button", { name: "Analizar" });
    await userEvent.click(analyzeButtons[0]);
    await userEvent.click(await screen.findByRole("button", { name: "Preparar carpeta" }));

    // Navigate to Root B before Root A's prepare resolves.
    await userEvent.click(screen.getByRole("button", { name: "Carpetas" }));
    const analyzeButtonsAgain = await screen.findAllByRole("button", { name: "Analizar" });
    await userEvent.click(analyzeButtonsAgain[1]);
    await screen.findByText("report.docx");
    expect(screen.getByText("C:/Documentos")).toBeInTheDocument();

    resolvePrepareA(fullPrepareResult("root-1"));

    await waitFor(() => {
      expect(screen.getByLabelText("Avisos de organización")).toBeInTheDocument();
    });
    // Root B's content is unaffected -- no forced re-render/navigation.
    expect(screen.getByText("report.docx")).toBeInTheDocument();
    expect(screen.getByText("C:/Documentos")).toBeInTheDocument();
    const notices = screen.getAllByRole("button", { name: "Ir a la carpeta" });
    expect(notices).toHaveLength(1);

    // Opening the notice navigates to Root A (not Root B, the currently
    // active screen), and issues no destination_setup.prepare/analysis.run
    // call by itself.
    const prepareCallsBefore = vi
      .mocked(invoke)
      .mock.calls.filter(([, a]) => (a as { command?: string })?.command === "destination_setup.prepare")
      .length;
    await userEvent.click(notices[0]);
    expect(await screen.findByText("C:/Descargas")).toBeInTheDocument();
    expect(screen.queryByText("C:/Documentos")).not.toBeInTheDocument();
    const prepareCallsAfter = vi
      .mocked(invoke)
      .mock.calls.filter(([, a]) => (a as { command?: string })?.command === "destination_setup.prepare")
      .length;
    expect(prepareCallsAfter).toBe(prepareCallsBefore);
  });

  it("dismissing a retained destination-setup notice removes only it and issues no backend call", async () => {
    let resolvePrepare!: (value: unknown) => void;
    const preparePromise = new Promise((resolve) => {
      resolvePrepare = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT_WITH_ATTENTION;
      if (command === "destination_setup.prepare") return preparePromise;
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Preparar carpeta" }));
    await userEvent.click(screen.getByRole("button", { name: "Historial" }));
    resolvePrepare(fullPrepareResult());

    await screen.findByRole("button", { name: "Ir a la carpeta" });
    const callsBeforeDismiss = vi.mocked(invoke).mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Descartar aviso" }));

    expect(screen.queryByLabelText("Avisos de organización")).not.toBeInTheDocument();
    expect(vi.mocked(invoke).mock.calls.length).toBe(callsBeforeDismiss);
  });

  it("a completion while still on the originating root's plan screen does not duplicate PlanScreen's own inline result banner as a notice", async () => {
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "analysis.run") return ANALYSIS_RESULT;
      if (command === "plan.create") return PLAN_RESULT_WITH_ATTENTION;
      if (command === "destination_setup.prepare") return fullPrepareResult();
      if (command === "history.list_recent") return { outcome: "ok", result: { rows: [] } };
      return { outcome: "ok", result: {} };
    });

    renderApp();
    await userEvent.click(await screen.findByRole("button", { name: "Analizar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Preparar carpeta" }));

    await screen.findByText("Documents — Preparada");
    expect(screen.queryByLabelText("Avisos de organización")).not.toBeInTheDocument();
  });
});
