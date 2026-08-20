import { X } from "lucide-react";
import type { RetainedCompletion } from "../../lib/completionInbox";
import { completionPresentation, guidanceForOutcome, type ApplyOutcome } from "../../lib/outcomeMessages";
import { Banner } from "./Banner";
import { Button } from "./Button";
import { IconButton } from "./IconButton";

/** Renders exactly one RetainedCompletion entry -- never computes what it
 * renders, only classifies (via completionPresentation) and dispatches to
 * one of the three approved presentations (FA-017.1 §19a). */
export function CompletionNotice({
  entry,
  onOpen,
  onDismiss,
}: {
  entry: RetainedCompletion<ApplyOutcome>;
  onOpen: () => void;
  onDismiss: () => void;
}) {
  const presentation = completionPresentation(entry.outcome);

  const dismiss = (
    <IconButton label="Descartar aviso" onClick={onDismiss}>
      <X size={14} />
    </IconButton>
  );

  if (presentation.kind === "result") {
    return (
      <Banner
        severity="info"
        title="Organización terminada"
        detail={presentation.result.summaryMessage.title}
        action={
          <div className="flex items-center gap-2">
            <Button variant="primary" onClick={onOpen}>
              Ver resultado
            </Button>
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
        action={dismiss}
      />
    );
  }

  const guidance = guidanceForOutcome(entry.outcome, "apply")!;
  return (
    <Banner
      severity="attention"
      title={guidance.title}
      detail={guidance.detail}
      action={
        <div className="flex items-center gap-2">
          <Button variant="primary" onClick={onOpen}>
            Ver historial
          </Button>
          {dismiss}
        </div>
      }
    />
  );
}
