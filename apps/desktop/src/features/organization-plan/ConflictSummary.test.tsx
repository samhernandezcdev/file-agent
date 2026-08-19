import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DestinationSetupItemResultView, PlanAttentionView } from "@file-agent/desktop-types";
import { ConflictSummary } from "./ConflictSummary";

const ATTENTION: PlanAttentionView = {
  variant: "missing_destination_folder",
  categoryLabel: "Documento",
  destinationLabel: "Documents",
  destinationCategory: "documents",
  message: {
    title: "Falta preparar esta carpeta",
    detail: "5 archivos están listos para clasificarse como Documento, pero falta:\n\nDocuments",
    severity: "attention",
    suggestedAction: "reanalyze",
  },
  affectedFilenames: ["a.pdf", "b.pdf"],
};

afterEach(() => vi.clearAllMocks());

describe("ConflictSummary", () => {
  it("shows 'Preparar carpeta' by default, no 'Analizar de nuevo' button", () => {
    render(
      <ConflictSummary
        attention={ATTENTION}
        onReanalyze={vi.fn()}
        onPrepare={vi.fn()}
        preparing={false}
        result={undefined}
      />,
    );

    expect(screen.getByRole("button", { name: "Preparar carpeta" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Analizar de nuevo" })).not.toBeInTheDocument();
    expect(screen.getByText("Falta preparar esta carpeta")).toBeInTheDocument();
  });

  it("calls onPrepare when 'Preparar carpeta' is clicked", async () => {
    const onPrepare = vi.fn();
    render(
      <ConflictSummary
        attention={ATTENTION}
        onReanalyze={vi.fn()}
        onPrepare={onPrepare}
        preparing={false}
        result={undefined}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Preparar carpeta" }));
    expect(onPrepare).toHaveBeenCalledTimes(1);
  });

  it("renders a result state instead of the panel once a result is present, with 'Analizar de nuevo'", () => {
    const result: DestinationSetupItemResultView = {
      destinationCategory: "documents",
      destinationLabel: "Documents",
      status: "prepared",
      message: {
        title: "Preparada",
        detail: "FileAgent creó esta carpeta.",
        severity: "info",
        suggestedAction: "none",
      },
    };
    render(
      <ConflictSummary
        attention={ATTENTION}
        onReanalyze={vi.fn()}
        onPrepare={vi.fn()}
        preparing={false}
        result={result}
      />,
    );

    expect(screen.queryByRole("button", { name: "Preparar carpeta" })).not.toBeInTheDocument();
    expect(screen.getByText("Documents — Preparada")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analizar de nuevo" })).toBeInTheDocument();
  });

  it("never implies creation for an already_available result", () => {
    const result: DestinationSetupItemResultView = {
      destinationCategory: "documents",
      destinationLabel: "Documents",
      status: "already_available",
      message: {
        title: "Ya estaba disponible",
        detail: "Esta carpeta ya existía.",
        severity: "info",
        suggestedAction: "none",
      },
    };
    render(
      <ConflictSummary
        attention={ATTENTION}
        onReanalyze={vi.fn()}
        onPrepare={vi.fn()}
        preparing={false}
        result={result}
      />,
    );

    expect(screen.getByText("Documents — Ya estaba disponible")).toBeInTheDocument();
    expect(screen.queryByText(/Preparada/)).not.toBeInTheDocument();
  });
});
