import type {
  BatchApplyResultView,
  DestinationSetupResultView,
  ManagedRootUnavailableResultView,
  UndoResultView,
  UserMessageView,
} from "@file-agent/desktop-types";
import type { RustOutcome } from "../desktop";

export type NonOkGuidance = { title: string; detail: string };

/** The apply.items RustOutcome shape, exported once here (mirroring
 * DestinationSetupOutcome below) so CompletionNotice.tsx has a canonical
 * type argument for RetainedCompletion<TOutcome> without re-deriving it. */
export type ApplyOutcome = RustOutcome<BatchApplyResultView | ManagedRootUnavailableResultView>;

/** FA-017.4 §2: the destination_setup.prepare RustOutcome shape,
 * exported once here so App.tsx and DestinationSetupCompletionNotice.tsx
 * share exactly one definition instead of each re-deriving it from
 * `desktop.destinationSetup.prepare`'s return type. */
export type DestinationSetupOutcome = RustOutcome<
  DestinationSetupResultView | ManagedRootUnavailableResultView
>;

export type OutcomeContext =
  | "apply"
  | "review"
  | "managed_root"
  | "undo_restore"
  | "destination_setup";

const UNKNOWN_DETAIL_BY_CONTEXT: Record<OutcomeContext, string> = {
  apply: "Revisa el historial para confirmar qué se organizó antes de intentarlo de nuevo.",
  review: "Actualizaremos la vista para mostrar el estado más reciente antes de tu próxima decisión.",
  managed_root: "Actualizaremos la lista de carpetas para mostrar el estado más reciente.",
  undo_restore: "Revisa la carpeta original para confirmar si el archivo ya está ahí.",
  // FA-017.2: deliberately never points to Historial -- there is no
  // destination-setup activity surface there (§12 of the design). A fresh
  // "Analizar de nuevo" fully resolves the uncertainty product-wise (the
  // next analysis either shows the folder or doesn't), even though it
  // can't prove who created it.
  destination_setup:
    "Analiza la carpeta de nuevo para comprobar su estado antes de intentarlo otra vez.",
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
  throw new Error(`outcomeMessages: unhandled outcome variant: ${JSON.stringify(x)}`);
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

/** FA-017.5 Part 26: Undo's own retained-completion outcome shape.
 * `transactionId` is carried alongside the RustOutcome itself (not
 * recoverable from every outcome variant -- e.g. unknown_mutation_outcome
 * carries no UndoResultView at all) since the notice/correlation logic
 * needs it regardless of which variant resolved. Known only at the
 * mutate()-call site, where the transaction being undone is always
 * already in scope. */
export type UndoOutcome = {
  transactionId: string;
  result: RustOutcome<UndoResultView>;
};

/** FA-017.5 Part 28: the Undo analog of CompletionPresentation/
 * DestinationSetupCompletionPresentation -- its own, separate type and
 * function (never sharing a body with the other two, same "SHARED FIFO
 * MECHANICS != SHARED PRODUCT SEMANTICS" principle). Deliberately
 * collapses UndoResultView's own succeeded/rejected/failed status into
 * "succeeded"/"rejected" HERE (the one designated place RustOutcome/DTO
 * shapes become presentation classes) so every consumer -- including
 * files the no-raw-status-branching guard covers -- only ever branches on
 * this presentation `kind`, never on a raw `status` string. */
export type UndoCompletionPresentation =
  | { kind: "succeeded"; result: UndoResultView }
  | { kind: "rejected"; message: UserMessageView }
  | { kind: "unknown" };

export function undoCompletionPresentation(
  outcome: UndoOutcome,
): UndoCompletionPresentation {
  const result = outcome.result;
  switch (result.outcome) {
    case "ok": {
      const undo = result.result;
      if (undo.status === "succeeded") {
        return { kind: "succeeded", result: undo };
      }
      // rejected or failed -- undo_result_view (backend) always populates
      // `message` for both non-succeeded statuses, never for succeeded.
      return { kind: "rejected", message: undo.message as UserMessageView };
    }
    case "unknown_mutation_outcome":
      return { kind: "unknown" };
    case "product_error":
    case "retryable_interrupted":
    case "transport_unavailable": {
      const guidance = guidanceForOutcome(result, "undo_restore")!; // never null here
      return {
        kind: "rejected",
        message: {
          title: guidance.title,
          detail: guidance.detail,
          severity: "error",
          suggestedAction: "none",
        },
      };
    }
    default:
      return assertNever(result);
  }
}

/** FA-017.4 §2/§3: the destination-setup analog of CompletionPresentation
 * above -- deliberately a SEPARATE type and a SEPARATE function, not a
 * shared/parametrized one. The two outcome shapes
 * (BatchApplyResultView vs DestinationSetupResultView) are different
 * DTOs with different product meaning (a batch of file moves vs a batch
 * of folder creations); collapsing them into one function would need an
 * internal branch on which DTO it received, which defeats the point of
 * each switch being independently exhaustive. Destination setup is never
 * routed through History (FA-017.2 §12, unchanged) -- there is no
 * `"result"` case here that ever suggests it, and callers must never add
 * one. */
export type DestinationSetupCompletionPresentation =
  | { kind: "result"; result: DestinationSetupResultView }
  | { kind: "known_no_result"; message: UserMessageView }
  | { kind: "unknown" };

/** Classifies an ALREADY FINAL destination_setup.prepare RustOutcome.
 * Mirrors completionPresentation's shape exactly but never calls it --
 * see the type's own docstring for why. */
export function destinationSetupCompletionPresentation(
  outcome: RustOutcome<DestinationSetupResultView | ManagedRootUnavailableResultView>,
): DestinationSetupCompletionPresentation {
  switch (outcome.outcome) {
    case "ok": {
      const result = outcome.result;
      switch (result.outcome) {
        case "ok":
          return { kind: "result", result };
        case "managed_root_unavailable":
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
      const guidance = guidanceForOutcome(outcome, "destination_setup")!; // never null here
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
