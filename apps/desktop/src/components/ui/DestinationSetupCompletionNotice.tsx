import { X } from "lucide-react";
import type { RetainedCompletion } from "../../lib/completionInbox";
import type { DestinationSetupOutcome } from "../../lib/outcomeMessages";
import { destinationSetupCompletionPresentation, guidanceForOutcome } from "../../lib/outcomeMessages";
import { Banner } from "./Banner";
import { Button } from "./Button";
import { IconButton } from "./IconButton";

/** FA-017.4 §2: renders exactly one retained destination_setup.prepare
 * completion -- structurally parallel to CompletionNotice.tsx (same
 * primitives, same dismiss affordance) but with distinct product
 * semantics, never blindly copied:
 *
 * - the primary action is always "Ir a la carpeta" (there is no
 *   destination-setup results screen to open, unlike apply's "Ver
 *   resultado" -- FA-017.2 §12 keeps this feature out of every product
 *   surface except the plan screen itself)
 * - History is never offered, for any case, including UNKNOWN (FA-017.2
 *   §12/§15, unchanged: a fresh "Analizar de nuevo" on the plan screen
 *   itself is what resolves the uncertainty, not a History lookup)
 * - navigating there never itself reanalyzes, prepares again, or
 *   applies -- NOTICE NAVIGATION != REANALYSIS; the existing
 *   FA-017.2/017.3 invalidated-plan gate is what requires the user's own
 *   explicit "Analizar de nuevo" once they arrive */
export function DestinationSetupCompletionNotice({
  entry,
  onOpen,
  onDismiss,
}: {
  entry: RetainedCompletion<DestinationSetupOutcome>;
  onOpen: () => void;
  onDismiss: () => void;
}) {
  const presentation = destinationSetupCompletionPresentation(entry.outcome);

  const dismiss = (
    <IconButton label="Descartar aviso" onClick={onDismiss}>
      <X size={14} />
    </IconButton>
  );

  const goToFolder = (
    <Button variant="primary" onClick={onOpen}>
      Ir a la carpeta
    </Button>
  );

  if (presentation.kind === "result") {
    // The backend's own, already provenance-aware summaryMessage
    // (FA-017.2 §18) -- rendered verbatim, exactly like every other
    // destination-setup surface. Covers KNOWN full success, KNOWN
    // partial success, and KNOWN none-prepared uniformly: the DTO's own
    // message already distinguishes them truthfully, never fabricated
    // here.
    return (
      <Banner
        severity={presentation.result.summaryMessage.severity as "info" | "attention" | "error"}
        title="FileAgent terminó de preparar carpetas"
        detail={presentation.result.summaryMessage.title}
        action={
          <div className="flex items-center gap-2">
            {goToFolder}
            {dismiss}
          </div>
        }
      />
    );
  }

  if (presentation.kind === "known_no_result") {
    return (
      <Banner
        severity="error"
        title={presentation.message.title}
        detail={presentation.message.detail}
        action={
          <div className="flex items-center gap-2">
            {goToFolder}
            {dismiss}
          </div>
        }
      />
    );
  }

  // UNKNOWN -- never claims success or failure. Same guidance copy the
  // in-place banner already uses (OutcomeContext "destination_setup"),
  // never a History action.
  const guidance = guidanceForOutcome(entry.outcome, "destination_setup")!;
  return (
    <Banner
      severity="attention"
      title={guidance.title}
      detail={guidance.detail}
      action={
        <div className="flex items-center gap-2">
          {goToFolder}
          {dismiss}
        </div>
      }
    />
  );
}
