import { X } from "lucide-react";
import type { RetainedCompletion } from "../../lib/completionInbox";
import type { UndoOutcome } from "../../lib/outcomeMessages";
import { guidanceForOutcome, undoCompletionPresentation } from "../../lib/outcomeMessages";
import { Banner } from "./Banner";
import { Button } from "./Button";
import { IconButton } from "./IconButton";

/** FA-017.5 Part 27: renders exactly one retained recovery.undo_transaction
 * completion -- structurally parallel to CompletionNotice.tsx/
 * DestinationSetupCompletionNotice.tsx (same primitives, same dismiss
 * affordance) but with its own product semantics, never blindly copied:
 *
 * - the only action is "Ver historial", which navigates to the EXACT
 *   originating batch's detail screen (`entry.correlationId` -- a batchId
 *   for this notice kind, never a managedRootId) -- there is no dedicated
 *   Undo results screen, and the detail screen's own refetch is what
 *   shows the truthful, current state
 * - navigating there never itself retries the Undo, starts a new one, or
 *   infers success/failure -- NOTICE NAVIGATION != FILESYSTEM MUTATION,
 *   the same invariant Part 9/26 require */
export function UndoCompletionNotice({
  entry,
  onOpen,
  onDismiss,
}: {
  entry: RetainedCompletion<UndoOutcome>;
  onOpen: () => void;
  onDismiss: () => void;
}) {
  const presentation = undoCompletionPresentation(entry.outcome);

  const dismiss = (
    <IconButton label="Descartar aviso" onClick={onDismiss}>
      <X size={14} />
    </IconButton>
  );

  const viewHistory = (
    <Button variant="primary" onClick={onOpen}>
      Ver historial
    </Button>
  );

  if (presentation.kind === "succeeded") {
    return (
      <Banner
        severity="info"
        title="Cambio deshecho"
        detail="FileAgent devolvió el archivo a su ubicación original."
        action={
          <div className="flex items-center gap-2">
            {viewHistory}
            {dismiss}
          </div>
        }
      />
    );
  }

  if (presentation.kind === "rejected") {
    return (
      <Banner
        severity="error"
        title={presentation.message.title}
        detail={presentation.message.detail}
        action={
          <div className="flex items-center gap-2">
            {viewHistory}
            {dismiss}
          </div>
        }
      />
    );
  }

  // UNKNOWN -- never claims success or failure. Same guidance copy the
  // in-place undo guidance already uses (OutcomeContext "undo_restore").
  const guidance = guidanceForOutcome(entry.outcome.result, "undo_restore")!;
  return (
    <Banner
      severity="attention"
      title={guidance.title}
      detail={guidance.detail}
      action={
        <div className="flex items-center gap-2">
          {viewHistory}
          {dismiss}
        </div>
      }
    />
  );
}
