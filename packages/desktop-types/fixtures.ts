// Compile-time-only contract check (FA-017 design §"TYPE GENERATION"):
// `satisfies` proves these object literals structurally match the
// generated interfaces. This file is never imported at runtime -- it
// exists purely so `tsc --noEmit` fails the build if the generated types
// and this fixture ever drift apart (e.g. a field renamed on the Python
// side without regenerating).

import type {
  ManagedRootView,
  PlanItemView,
  UserMessageView,
} from "./generated/index.js";

export const exampleUserMessage = {
  title: "No se pudo agregar esta carpeta.",
  detail: "Esta carpeta ya está agregada.",
  severity: "error",
  suggestedAction: "none",
} satisfies UserMessageView;

export const exampleManagedRoot = {
  id: "8a3e6b0e-2f4a-4b8b-9b8a-0f2e6f1a2b3c",
  displayPath: "C:/Users/Ana/Descargas",
  status: "available",
} satisfies ManagedRootView;

export const examplePlanItem = {
  actionId: "8a3e6b0e-2f4a-4b8b-9b8a-0f2e6f1a2b3c",
  filename: "invoice.pdf",
  sourceDisplayPath: "C:/Users/Ana/Descargas/invoice.pdf",
  destinationDisplayPath: null,
  categoryLabel: "Documento",
  status: "ready",
  title: "Listo para organizar",
  detail: "Este archivo está listo para organizarse.",
  severity: "info",
  selectable: true,
} satisfies PlanItemView;
