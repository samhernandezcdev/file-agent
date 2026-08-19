import type { BatchApplyResultView } from "@file-agent/desktop-types";
import { Banner, type BannerSeverity } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";
import { Collapsible } from "../../components/ui/Collapsible";

/** Primary CTA is "Ver historial" (FA-017.1 §20) -- History/Undo
 * discoverability is a core trust differentiator, and this is the
 * highest-leverage moment to reinforce that everything is reversible.
 * Never fabricates success/failure text: every word comes from the
 * backend's own summaryMessage, chosen severity included -- a partial
 * result is never silently collapsed into a generic error. */
export function ApplyResultsScreen({
  result,
  onViewHistory,
  onDone,
}: {
  result: BatchApplyResultView;
  onViewHistory: () => void;
  onDone: () => void;
}) {
  const { summary } = result;
  const isPartial = summary.applied < summary.selected;

  return (
    <section aria-labelledby="apply-results-heading">
      <h1 id="apply-results-heading" className="mb-3 text-xl font-semibold text-foreground">
        Resultado
      </h1>
      <Banner
        severity={result.summaryMessage.severity as BannerSeverity}
        title={result.summaryMessage.title}
        detail={result.summaryMessage.detail}
      />
      <p className="mt-3 text-sm text-foreground-muted">
        {summary.applied} de {summary.selected} archivos se organizaron
      </p>

      {isPartial && result.items.length > 0 ? (
        <div className="mt-3">
          <Collapsible triggerLabel="Ver detalles">
            <ul aria-label="Archivos procesados" className="flex flex-col gap-1">
              {result.items.map((item) => (
                <li key={item.policyDecisionId} className="text-sm text-foreground-muted">
                  <span className="font-medium text-foreground">{item.filename ?? "Archivo"}</span>
                  {" — "}
                  {item.message.title}
                </li>
              ))}
            </ul>
          </Collapsible>
        </div>
      ) : null}

      <div className="mt-6 flex items-center gap-3">
        <Button variant="primary" onClick={onViewHistory}>
          Ver historial
        </Button>
        <Button onClick={onDone}>Volver a la carpeta</Button>
      </div>
    </section>
  );
}
