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
    expect(await screen.findByText(/organiza tus archivos sin perder el control/i)).toBeInTheDocument();
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
    await screen.findByText(/organiza tus archivos sin perder el control/i);

    await userEvent.click(screen.getByRole("button", { name: "Elegir carpeta" }));

    expect(open).toHaveBeenCalledWith({ directory: true, multiple: false });
  });

  it("performs no registration when the folder picker is canceled", async () => {
    vi.mocked(invoke).mockResolvedValue({ outcome: "ok", result: { roots: [] } });
    vi.mocked(open).mockResolvedValue(null);
    renderScreen();
    await screen.findByText(/organiza tus archivos sin perder el control/i);

    await userEvent.click(screen.getByRole("button", { name: "Elegir carpeta" }));

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
    await screen.findByText(/organiza tus archivos sin perder el control/i);

    await userEvent.click(screen.getByRole("button", { name: "Elegir carpeta" }));

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

describe("ManagedRootsScreen -- first-run hero (FA-017.6)", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    vi.mocked(open).mockReset();
    vi.mocked(invoke).mockResolvedValue({ outcome: "ok", result: { roots: [] } });
  });
  afterEach(() => vi.clearAllMocks());

  it("shows the exact final short explanation", async () => {
    renderScreen();
    expect(
      await screen.findByText(
        "Elige una carpeta. FileAgent analizará los archivos y te mostrará los cambios antes de organizar.",
      ),
    ).toBeInTheDocument();
  });

  it("renders exactly 3 non-interactive workflow stages with the exact labels", async () => {
    renderScreen();
    await screen.findByText("Organiza tus archivos sin perder el control");

    for (const label of ["Elige una carpeta", "Revisa los cambios", "Organiza"]) {
      const stage = screen.getByText(label);
      expect(stage.closest("button")).toBeNull();
      expect(stage.closest('[role="button"]')).toBeNull();
    }
  });

  it("renders exactly 3 trust statements with the exact final copy", async () => {
    renderScreen();
    await screen.findByText("Organiza tus archivos sin perder el control");

    const list = screen.getByText(/Revisa antes de organizar/).closest("ul") as HTMLElement;
    expect(list.children).toHaveLength(3);
    expect(screen.getByText(/Revisa antes de organizar/)).toBeInTheDocument();
    expect(screen.getByText(/No reemplazamos archivos existentes/)).toBeInTheDocument();
    expect(screen.getByText(/Puedes deshacer cambios/)).toBeInTheDocument();
  });

  it("'Elegir carpeta' is the sole dominant action on the hero", async () => {
    renderScreen();
    await screen.findByText("Organiza tus archivos sin perder el control");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Elegir carpeta" })).toBeInTheDocument();
  });

  it("hero disappears once a root exists", async () => {
    vi.mocked(invoke).mockResolvedValue({
      outcome: "ok",
      result: { roots: [{ id: "a", displayPath: "C:/Descargas", status: "available" }] },
    });
    renderScreen();
    await screen.findByText("C:/Descargas");
    expect(
      screen.queryByText("Organiza tus archivos sin perder el control"),
    ).not.toBeInTheDocument();
  });

  it("introduces no localStorage or sessionStorage usage", async () => {
    const setLocal = vi.spyOn(Storage.prototype, "setItem");
    const getLocal = vi.spyOn(Storage.prototype, "getItem");
    renderScreen();
    await screen.findByText("Organiza tus archivos sin perder el control");
    await userEvent.click(screen.getByRole("button", { name: "Elegir carpeta" }));
    expect(setLocal).not.toHaveBeenCalled();
    expect(getLocal).not.toHaveBeenCalled();
    setLocal.mockRestore();
    getLocal.mockRestore();
  });
});

describe("ManagedRootsScreen -- root row action hierarchy (FA-017.6)", () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset();
    vi.mocked(open).mockReset();
  });
  afterEach(() => vi.clearAllMocks());

  function mockOneRoot() {
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") {
        return {
          outcome: "ok",
          result: { roots: [{ id: "root-1", displayPath: "C:/Descargas", status: "available" }] },
        };
      }
      return { outcome: "ok", result: {} };
    });
  }

  it("'Analizar' is the only primary-styled action in the row", async () => {
    mockOneRoot();
    renderScreen();
    await screen.findByText("C:/Descargas");
    const analyzeButton = screen.getByRole("button", { name: "Analizar" });
    expect(analyzeButton.className).toContain("bg-primary");
    const removeButton = screen.getByRole("button", { name: "Dejar de organizar esta carpeta" });
    expect(removeButton.className).not.toContain("bg-primary");
  });

  it("remove action remains present, accessible, and keyboard reachable", async () => {
    mockOneRoot();
    renderScreen();
    await screen.findByText("C:/Descargas");
    const removeButton = screen.getByRole("button", { name: "Dejar de organizar esta carpeta" });
    expect(removeButton).toBeInTheDocument();
    expect(removeButton.tagName).toBe("BUTTON");
  });

  it("remove click still invokes the exact same mutation with the exact root id", async () => {
    mockOneRoot();
    renderScreen();
    await screen.findByText("C:/Descargas");
    await userEvent.click(screen.getByRole("button", { name: "Dejar de organizar esta carpeta" }));

    await waitFor(() => {
      const removeCall = vi
        .mocked(invoke)
        .mock.calls.find(
          ([, args]) => (args as { command?: string })?.command === "managed_roots.remove",
        );
      expect(removeCall).toBeDefined();
      expect((removeCall?.[1] as { params: { managedRootId: string } }).params.managedRootId).toBe(
        "root-1",
      );
    });
  });

  it("remove pending state disables the control against duplicate interaction", async () => {
    let resolveRemove!: (value: unknown) => void;
    const removePromise = new Promise((resolve) => {
      resolveRemove = resolve;
    });
    vi.mocked(invoke).mockImplementation(async (_cmd, args) => {
      const command = (args as { command?: string })?.command;
      if (command === "managed_roots.list") {
        return {
          outcome: "ok",
          result: { roots: [{ id: "root-1", displayPath: "C:/Descargas", status: "available" }] },
        };
      }
      if (command === "managed_roots.remove") return removePromise;
      return { outcome: "ok", result: {} };
    });
    renderScreen();
    await screen.findByText("C:/Descargas");
    const removeButton = screen.getByRole("button", { name: "Dejar de organizar esta carpeta" });
    await userEvent.click(removeButton);
    expect(removeButton).toBeDisabled();
    resolveRemove({ outcome: "ok", result: { managedRootId: "root-1", status: "succeeded", message: null } });
  });
});
