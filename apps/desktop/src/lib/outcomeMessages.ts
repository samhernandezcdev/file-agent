import type {
  BatchApplyResultView,
  ManagedRootUnavailableResultView,
  UserMessageView,
} from "@file-agent/desktop-types";
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

/** FA-017.1 §19a: the three ways an apply completion is ever presented.
 * `RESULT` and `KNOWN_NO_RESULT` together are the "ordinary" subset subject
 * to the completion inbox's FIFO cap; `UNKNOWN` is never bounded. */
export type CompletionPresentation =
  | { kind: "result"; result: BatchApplyResultView }
  | { kind: "known_no_result"; message: UserMessageView }
  | { kind: "unknown" };

function assertNever(x: never): never {
  throw new Error(`completionPresentation: unhandled outcome variant: ${JSON.stringify(x)}`);
}

/** Classifies an ALREADY FINAL apply RustOutcome into its presentation
 * class. Never inspects STARTED, retry-safety, command name, or any
 * transport/process state -- all of that was already resolved by Rust
 * before this function runs (see FA-017's sidecar.rs RequestOutcome
 * construction). Exhaustive switch + assertNever so a future RustOutcome
 * (or nested BatchApplyResultView/ManagedRootUnavailableResultView union
 * member) is a compile error here, never a silent KNOWN_NO_RESULT. */
export function completionPresentation(
  outcome: RustOutcome<BatchApplyResultView | ManagedRootUnavailableResultView>,
): CompletionPresentation {
  switch (outcome.outcome) {
    case "ok": {
      const result = outcome.result;
      switch (result.outcome) {
        case "ok":
          return { kind: "result", result };
        case "managed_root_unavailable":
          // DTO already carries its own composed message; render verbatim.
          return { kind: "known_no_result", message: result.message };
        default:
          return assertNever(result);
      }
    }
    case "unknown_mutation_outcome":
      return { kind: "unknown" };
    case "product_error":
    case "retryable_interrupted":
    case "transport_unavailable": {
      const guidance = guidanceForOutcome(outcome, "apply")!; // never null here
      return {
        kind: "known_no_result",
        message: {
          title: guidance.title,
          detail: guidance.detail,
          severity: "error",
          suggestedAction: "none",
        },
      };
    }
    default:
      return assertNever(outcome);
  }
}
