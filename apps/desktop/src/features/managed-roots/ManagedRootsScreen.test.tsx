import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { ManagedRootsScreen } from "./ManagedRootsScreen";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

function renderScreen() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onAnalyze = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <ManagedRootsScreen onAnalyze={onAnalyze} />
    </QueryClientProvider>,
  );
  return { onAnalyze };
}

describe("ManagedRootsScreen", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    vi.mocked(open).mockReset();
  });
  afterEach(() => vi.clearAllMocks());

  it("shows the empty state when there are no managed roots", async () => {
    vi.mocked(invoke).mockResolvedValue({ outcome: "ok", result: { roots: [] } });
    renderScreen();
    expect(await screen.findByText(/organiza una carpeta con fileagent/i)).toBeInTheDocument();
  });

  it("renders roots and marks an unavailable one distinctly", async () => {
    vi.mocked(invoke).mockResolvedValue({
      outcome: "ok",
      result: {
        roots: [
          { id: "a", displayPath: "C:/Descargas", status: "available" },
          { id: "b", displayPath: "C:/Removida", status: "unavailable" },
        ],
      },
    });
    renderScreen();
    expect(await screen.findByText("C:/Descargas")).toBeInTheDocument();
    expect(await screen.findByText("C:/Removida")).toBeInTheDocument();
    expect(screen.getByText(/no disponible en este momento/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Agregar carpeta" })).toBeInTheDocument();
  });

  it("calls the native folder picker when 'Elegir una carpeta' is clicked", async () => {
    vi.mocked(invoke).mockResolvedValue({ outcome: "ok", result: { roots: [] } });
    vi.mocked(open).mockResolvedValue(null);
    renderScreen();
    await screen.findByText(/organiza una carpeta con fileagent/i);

    await userEvent.click(screen.getByRole("button", { name: "Elegir una carpeta" }));

    expect(open).toHaveBeenCalledWith({ directory: true, multiple: false });
  });

  it("performs no registration when the folder picker is canceled", async () => {
    vi.mocked(invoke).mockResolvedValue({ outcome: "ok", result: { roots: [] } });
    vi.mocked(open).mockResolvedValue(null);
    renderScreen();
    await screen.findByText(/organiza una carpeta con fileagent/i);

    await userEvent.click(screen.getByRole("button", { name: "Elegir una carpeta" }));

    await waitFor(() => {
      // Only the initial managed_roots.list call happened -- no
      // managed_roots.add call was ever issued for a canceled picker.
      const calls = vi.mocked(invoke).mock.calls;
      expect(calls.every(([command]) => command === "desktop_call")).toBe(true);
      const addCalls = calls.filter(
        ([, args]) => (args as { command?: string })?.command === "managed_roots.add",
      );
      expect(addCalls).toHaveLength(0);
    });
  });

  it("registers the picked folder when a real path is chosen", async () => {
    vi.mocked(invoke).mockResolvedValue({ outcome: "ok", result: { roots: [] } });
    vi.mocked(open).mockResolvedValue("C:/Users/Ana/Descargas");
    renderScreen();
    await screen.findByText(/organiza una carpeta con fileagent/i);

    await userEvent.click(screen.getByRole("button", { name: "Elegir una carpeta" }));

    await waitFor(() => {
      const addCall = vi
        .mocked(invoke)
        .mock.calls.find(
          ([, args]) => (args as { command?: string })?.command === "managed_roots.add",
        );
      expect(addCall).toBeDefined();
      expect((addCall?.[1] as { params: { path: string } }).params.path).toBe(
        "C:/Users/Ana/Descargas",
      );
    });
  });
});
