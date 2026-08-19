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
