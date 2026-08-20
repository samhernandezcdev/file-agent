import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { HistoryScreen } from "./HistoryScreen";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const ROOTS_RESULT = {
  outcome: "ok",
  result: { roots: [{ id: "root-1", displayPath: "C:/Descargas", status: "available" }] },
};

function entryRow(overrides: Record<string, unknown> = {}) {
  return {
    rowType: "entry",
    outcome: "found",
    batchId: "batch-1",
    startedAt: "2026-01-01T00:00:00Z",
    completedAt: "2026-01-01T00:00:01Z",
    status: "completed",
    selectedCount: 12,
    appliedCount: 10,
    notAppliedCount: 2,
    skippedCount: 0,
    invalidCount: 0,
    processedCount: 12,
    managedRootId: "root-1",
    items: null,
    summaryMessage: {
      title: "10 archivos se organizaron. 2 no se pudieron mover.",
      detail: "Revisa los archivos que no se movieron para ver más detalles.",
      severity: "attention",
      suggestedAction: "none",
    },
    recoveryMessage: null,
    ...overrides,
  };
}

function renderScreen(rows: unknown[]) {
  vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
    const command = (args as { command?: string })?.command;
    if (command === "history.list_recent") return { outcome: "ok", result: { rows } };
    if (command === "managed_roots.list") return ROOTS_RESULT;
    return { outcome: "ok", result: {} };
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onOpenBatch = vi.fn();
  const onChooseAnotherFolder = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <HistoryScreen onOpenBatch={onOpenBatch} onChooseAnotherFolder={onChooseAnotherFolder} />
    </QueryClientProvider>,
  );
  return { onOpenBatch, onChooseAnotherFolder };
}

describe("HistoryScreen -- compact operation cards (FA-017.5)", () => {
  beforeEach(() => vi.mocked(invoke).mockReset());
  afterEach(() => vi.clearAllMocks());

  it("renders one card per batch, showing root, date, and summary -- never file rows or paths", async () => {
    renderScreen([entryRow()]);
    expect(await screen.findByText("C:/Descargas")).toBeInTheDocument();
    expect(
      screen.getByText("10 archivos se organizaron. 2 no se pudieron mover."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Revisa los archivos que no se movieron para ver más detalles."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/report\.pdf/)).not.toBeInTheDocument();
  });

  it("shows the recoveryMessage title when present, opaquely, without a Deshacer button", async () => {
    renderScreen([
      entryRow({
        recoveryMessage: {
          title: "Puedes deshacer cambios",
          detail: "...",
          severity: "info",
          suggestedAction: "none",
        },
      }),
    ]);
    expect(await screen.findByText("Puedes deshacer cambios")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deshacer" })).not.toBeInTheDocument();
  });

  it("renders no recovery line at all when recoveryMessage is null", async () => {
    renderScreen([entryRow({ recoveryMessage: null })]);
    await screen.findByText("C:/Descargas");
    expect(screen.queryByText(/deshacer/i)).not.toBeInTheDocument();
  });

  it("has exactly one interactive action per card: 'Ver detalles'", async () => {
    renderScreen([entryRow()]);
    await screen.findByText("C:/Descargas");
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveTextContent("Ver detalles");
  });

  it("'Ver detalles' opens the exact batchId the card represents", async () => {
    const { onOpenBatch } = renderScreen([entryRow({ batchId: "batch-42" })]);
    await screen.findByText("C:/Descargas");
    await userEvent.click(screen.getByRole("button", { name: "Ver detalles" }));
    expect(onOpenBatch).toHaveBeenCalledWith("batch-42");
    expect(onOpenBatch).toHaveBeenCalledTimes(1);
  });

  it("renders an unavailable row with safe copy and no Ver detalles action", async () => {
    renderScreen([
      {
        rowType: "unavailable",
        batchId: "batch-bad",
        startedAt: null,
        message: {
          title: "No pudimos mostrar los detalles de esta operación.",
          detail: "No pudimos completar esta acción de forma segura.",
          severity: "error",
          suggestedAction: "none",
        },
      },
    ]);
    expect(
      await screen.findByText("No pudimos mostrar los detalles de esta operación."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ver detalles" })).not.toBeInTheDocument();
  });

  it("empty state shows title, detail, and 'Elegir otra carpeta' navigating to roots", async () => {
    const { onChooseAnotherFolder } = renderScreen([]);
    expect(await screen.findByText("Aún no hay actividad")).toBeInTheDocument();
    expect(
      screen.getByText("Cuando organices archivos, podrás revisar aquí los cambios realizados."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Elegir otra carpeta" }));
    expect(onChooseAnotherFolder).toHaveBeenCalledTimes(1);
  });
});
