import type { PlanAttentionView } from "@file-agent/desktop-types";
import { AlertTriangle } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { Collapsible } from "../../components/ui/Collapsible";

/** Pure rendering over a backend-supplied PlanAttentionView (FA-017.1
 * §18) -- selects a layout via `variant` only, and renders every word of
 * `message`/`destinationLabel`/`affectedFilenames` verbatim. Never
 * inspects reason_code (which never reaches this DTO), never derives
 * copy. Its only local state is the "Ver qué falta" expand/collapse,
 * owned by the shared Collapsible primitive. */
export function ConflictSummary({
  attention,
  onReanalyze,
}: {
  attention: PlanAttentionView;
  onReanalyze: () => void;
}) {
  // Only one variant exists today; a future variant is an intentional,
  // explicit addition to this switch -- never an inferred fallback.
  switch (attention.variant) {
    case "missing_destination_folder":
      return (
        <div className="mb-2 rounded-md border border-warning/30 bg-surface-muted p-3">
          <div className="flex gap-2">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
            <div className="flex-1">
              <p className="text-sm font-semibold text-foreground">{attention.message.title}</p>
              <p className="mt-1 whitespace-pre-line text-sm text-foreground-muted">
                {attention.message.detail}
              </p>
              <div className="mt-2 flex items-center gap-3">
                {attention.message.suggestedAction === "reanalyze" ? (
                  <Button variant="primary" onClick={onReanalyze}>
                    Analizar de nuevo
                  </Button>
                ) : null}
                <Collapsible triggerLabel="Ver qué falta">
                  <ul className="list-inside list-disc text-sm text-foreground-muted">
                    {attention.affectedFilenames.map((filename) => (
                      <li key={filename}>{filename}</li>
                    ))}
                  </ul>
                </Collapsible>
              </div>
            </div>
          </div>
        </div>
      );
  }
}
