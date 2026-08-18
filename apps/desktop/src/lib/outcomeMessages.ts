import type { RustOutcome } from "../desktop";

export type NonOkGuidance = { title: string; detail: string };

export type OutcomeContext = "apply" | "review" | "managed_root" | "undo_restore";

const UNKNOWN_DETAIL_BY_CONTEXT: Record<OutcomeContext, string> = {
  apply: "Revisa el historial para confirmar qué se organizó antes de intentarlo de nuevo.",
  review: "Actualizaremos la vista para mostrar el estado más reciente antes de tu próxima decisión.",
  managed_root: "Actualizaremos la lista de carpetas para mostrar el estado más reciente.",
  undo_restore: "Revisa la carpeta original para confirmar si el archivo ya está ahí.",
};

/** Never show success, never show a safe failure, never auto-retry: this
 * is the ONE place non-`ok` outcomes become Spanish copy, shared by every
 * feature so the UNKNOWN/transport wording never drifts between screens. */
export function guidanceForOutcome(
  outcome: RustOutcome<unknown>,
  context: OutcomeContext,
): NonOkGuidance | null {
  switch (outcome.outcome) {
    case "ok":
      return null;
    case "product_error":
      return { title: "No se pudo completar la acción.", detail: outcome.message };
    case "unknown_mutation_outcome":
      return {
        title: "No pudimos confirmar si la operación terminó.",
        detail: UNKNOWN_DETAIL_BY_CONTEXT[context],
      };
    case "retryable_interrupted":
      return {
        title: "Se interrumpió la conexión antes de empezar.",
        detail: "No se realizó ningún cambio. Puedes intentarlo de nuevo.",
      };
    case "transport_unavailable":
      return {
        title: "FileAgent no está disponible en este momento.",
        detail: outcome.message,
      };
  }
}
