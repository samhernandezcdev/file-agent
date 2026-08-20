import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { HistoryDetailScreen } from "./HistoryDetailScreen";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const ROOTS_RESULT = {
  outcome: "ok",
  result: { roots: [{ id: "root-1", displayPath: "C:/Descargas", status: "available" }] },
};

function batchEntry(items: unknown[]) {
  return {
    outcome: "ok",
    result: {
      outcome: "found",
      rowType: "entry",
      batchId: "batch-1",
      startedAt: "2026-01-01T00:00:00Z",
      completedAt: "2026-01-01T00:00:01Z",
      status: "completed",
      selectedCount: items.length,
      appliedCount: items.filter((i) => (i as { status: string }).status === "applied").length,
      notAppliedCount: items.filter((i) => (i as { status: string }).status !== "applied").length,
      skippedCount: 0,
      invalidCount: 0,
      processedCount: items.length,
      managedRootId: "root-1",
      items,
      summaryMessage: {
        title: "1 archivos se organizaron correctamente.",
        detail: "Todos los archivos seleccionados se movieron a su carpeta.",
        severity: "info",
        suggestedAction: "none",
      },
      recoveryMessage: null,
    },
  };
}

function appliedItem(overrides: Record<string, unknown> = {}) {
  return {
    policyDecisionId: "pd-1",
    inputIndex: 0,
    status: "applied",
    transactionId: "tx-1",
    reasonDetail: null,
    filename: "factura.pdf",
    sourceDisplayPath: "C:/Descargas/factura.pdf",
    destinationDisplayPath: "C:/Descargas/Documents/factura.pdf",
    undoAvailable: true,
    alreadyUndone: false,
    message: {
      title: "Organizado",
      detail: "Se movió de C:/Descargas/factura.pdf a C:/Descargas/Documents/factura.pdf.",
      severity: "info",
      suggestedAction: "none",
    },
    ...overrides,
  };
}

function mockInvoke(getBatchResult: unknown, undoResult?: unknown) {
  vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
    const command = (args as { command?: string })?.command;
    if (command === "history.get_batch") return getBatchResult;
    if (command === "managed_roots.list") return ROOTS_RESULT;
    if (command === "recovery.undo_transaction") return undoResult ?? { outcome: "ok", result: {} };
    return { outcome: "ok", result: {} };
  });
}

function renderScreen(onUndoCompleted = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onBack = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <HistoryDetailScreen batchId="batch-1" onBack={onBack} onUndoCompleted={onUndoCompleted} />
    </QueryClientProvider>,
  );
  return { onBack, onUndoCompleted };
}

describe("HistoryDetailScreen (FA-017.5)", () => {
  beforeEach(() => vi.mocked(invoke).mockReset());
  afterEach(() => vi.clearAllMocks());

  it("fetches authoritative detail via history.get_batch, not from any passed-in row", async () => {
    mockInvoke(batchEntry([appliedItem()]));
    renderScreen();
    expect(await screen.findByText("factura.pdf")).toBeInTheDocument();
    await waitFor(() => {
      const calls = vi
        .mocked(invoke)
        .mock.calls.filter(([, a]) => (a as { command?: string })?.command === "history.get_batch");
      expect(calls.length).toBeGreaterThan(0);
      const params = (calls[0][1] as { params: { batchId: string } }).params;
      expect(params.batchId).toBe("batch-1");
    });
  });

  it("shows filename first, then result, then source → destination", async () => {
    mockInvoke(batchEntry([appliedItem()]));
    renderScreen();
    await screen.findByText("factura.pdf");
    expect(screen.getByText("Organizado")).toBeInTheDocument();
    expect(
      screen.getByText("C:/Descargas/factura.pdf → C:/Descargas/Documents/factura.pdf"),
    ).toBeInTheDocument();
  });

  it("shows the reason (not a path) for a not-organized item with no destination path", async () => {
    mockInvoke(
      batchEntry([
        appliedItem({
          status: "not_applied",
          undoAvailable: false,
          destinationDisplayPath: null,
          message: {
            title: "No se organizó",
            detail: "Ya existe un archivo con ese nombre en la carpeta de destino.",
            severity: "error",
            suggestedAction: "none",
          },
        }),
      ]),
    );
    renderScreen();
    await screen.findByText("factura.pdf");
    expect(
      screen.getByText("Ya existe un archivo con ese nombre en la carpeta de destino."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/→/)).not.toBeInTheDocument();
  });

  it("old row with no filename renders the safe fallback, never 'undefined'", async () => {
    mockInvoke(batchEntry([appliedItem({ filename: null, sourceDisplayPath: null })]));
    renderScreen();
    expect(await screen.findAllByText("No pudimos identificar este archivo.")).not.toHaveLength(0);
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
  });

  it("renders 'Deshacer' only when undoAvailable is true", async () => {
    mockInvoke(batchEntry([appliedItem({ undoAvailable: true })]));
    renderScreen();
    await screen.findByText("factura.pdf");
    expect(screen.getByRole("button", { name: "Deshacer" })).toBeInTheDocument();
  });

  it("renders 'Cambio deshecho' with no Deshacer button when alreadyUndone is true", async () => {
    mockInvoke(batchEntry([appliedItem({ undoAvailable: false, alreadyUndone: true })]));
    renderScreen();
    await screen.findByText("factura.pdf");
    expect(screen.getByText("Cambio deshecho")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deshacer" })).not.toBeInTheDocument();
  });

  it("renders no undo-related affordance when neither undoAvailable nor alreadyUndone", async () => {
    mockInvoke(
      batchEntry([
        appliedItem({ status: "not_applied", undoAvailable: false, alreadyUndone: false }),
      ]),
    );
    renderScreen();
    await screen.findByText("factura.pdf");
    expect(screen.queryByRole("button", { name: "Deshacer" })).not.toBeInTheDocument();
    expect(screen.queryByText("Cambio deshecho")).not.toBeInTheDocument();
  });

  it("shows the confirmation dialog copy before undoing", async () => {
    mockInvoke(batchEntry([appliedItem()]));
    renderScreen();
    await userEvent.click(await screen.findByRole("button", { name: "Deshacer" }));
    expect(screen.getByText("¿Deshacer este cambio?")).toBeInTheDocument();
    expect(
      screen.getByText(
        "FileAgent intentará devolver el archivo a su ubicación original. No reemplazará archivos existentes.",
      ),
    ).toBeInTheDocument();
  });

  it("shows 'Deshaciendo…' while pending and prevents a duplicate submission", async () => {
    let resolveUndo!: (value: unknown) => void;
    const undoPromise = new Promise((resolve) => {
      resolveUndo = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "history.get_batch") return batchEntry([appliedItem()]);
      if (command === "managed_roots.list") return ROOTS_RESULT;
      if (command === "recovery.undo_transaction") return undoPromise;
      return { outcome: "ok", result: {} };
    });
    renderScreen();
    await userEvent.click(await screen.findByRole("button", { name: "Deshacer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Sí, deshacer" }));

    const busyButton = await screen.findByRole("button", { name: "Deshaciendo…" });
    expect(busyButton).toBeDisabled();

    resolveUndo({
      outcome: "ok",
      result: {
        transactionId: "tx-1",
        recoveryId: "rec-1",
        status: "succeeded",
        restoredDisplayPath: "C:/Descargas/factura.pdf",
        message: null,
      },
    });
    const undoCalls = () =>
      vi
        .mocked(invoke)
        .mock.calls.filter(([, a]) => (a as { command?: string })?.command === "recovery.undo_transaction");
    await waitFor(() => expect(undoCalls()).toHaveLength(1));
  });

  it("calls onUndoCompleted with the batchId and transaction outcome on success", async () => {
    mockInvoke(batchEntry([appliedItem()]), {
      outcome: "ok",
      result: {
        transactionId: "tx-1",
        recoveryId: "rec-1",
        status: "succeeded",
        restoredDisplayPath: "C:/Descargas/factura.pdf",
        message: null,
      },
    });
    const onUndoCompleted = vi.fn();
    renderScreen(onUndoCompleted);
    await userEvent.click(await screen.findByRole("button", { name: "Deshacer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Sí, deshacer" }));

    await waitFor(() => expect(onUndoCompleted).toHaveBeenCalledTimes(1));
    const [batchId, outcome] = onUndoCompleted.mock.calls[0];
    expect(batchId).toBe("batch-1");
    expect(outcome.transactionId).toBe("tx-1");
    expect(outcome.result.outcome).toBe("ok");
  });

  it("shows truthful rejection copy in place when Undo is rejected", async () => {
    mockInvoke(batchEntry([appliedItem()]), {
      outcome: "ok",
      result: {
        transactionId: "tx-1",
        recoveryId: null,
        status: "rejected",
        restoredDisplayPath: null,
        message: {
          title: "No pudimos deshacer este cambio.",
          detail: "La ubicación original ya contiene un archivo con ese nombre. No reemplazamos ningún archivo.",
          severity: "error",
          suggestedAction: "none",
        },
      },
    });
    renderScreen();
    await userEvent.click(await screen.findByRole("button", { name: "Deshacer" }));
    await userEvent.click(await screen.findByRole("button", { name: "Sí, deshacer" }));

    expect(
      await screen.findByText(
        "La ubicación original ya contiene un archivo con ese nombre. No reemplazamos ningún archivo.",
      ),
    ).toBeInTheDocument();
  });

  it("original 'Organizado' fact and source→destination remain visible after a successful Undo", async () => {
    mockInvoke(batchEntry([appliedItem({ undoAvailable: false, alreadyUndone: true })]));
    renderScreen();
    await screen.findByText("factura.pdf");
    expect(screen.getByText("Organizado")).toBeInTheDocument();
    expect(
      screen.getByText("C:/Descargas/factura.pdf → C:/Descargas/Documents/factura.pdf"),
    ).toBeInTheDocument();
    expect(screen.getByText("Cambio deshecho")).toBeInTheDocument();
  });

  it("shows the recoveryMessage title when present on the entry", async () => {
    const entry = batchEntry([appliedItem()]);
    (entry.result as { recoveryMessage: unknown }).recoveryMessage = {
      title: "Puedes deshacer cambios",
      detail: "...",
      severity: "info",
      suggestedAction: "none",
    };
    mockInvoke(entry);
    renderScreen();
    expect(await screen.findByText("Puedes deshacer cambios")).toBeInTheDocument();
  });

  it("back navigation calls onBack", async () => {
    mockInvoke(batchEntry([appliedItem()]));
    const { onBack } = renderScreen();
    await screen.findByText("factura.pdf");
    await userEvent.click(screen.getByText("← Historial"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("renders a safe error state for an unavailable batch, with a back action", async () => {
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "history.get_batch") {
        return { outcome: "ok", result: { outcome: "unavailable", message: { title: "No pudimos mostrar los detalles de esta operación.", detail: "x", severity: "error", suggestedAction: "none" } } };
      }
      return { outcome: "ok", result: {} };
    });
    const { onBack } = renderScreen();
    expect(
      await screen.findByText("No pudimos mostrar los detalles de esta operación."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByText("← Historial"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
