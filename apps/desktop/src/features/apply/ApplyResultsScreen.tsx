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
  onReanalyze,
}: {
  result: BatchApplyResultView;
  onViewHistory: () => void;
  onDone: () => void;
  /** FA-017.4 Part 14: direct same-root reanalysis, reusing
   * result.managedRootId (no re-fetch of the roots list needed). `null`
   * when the originating root's id could not be resolved -- the existing
   * "Volver a la carpeta" action is the fallback in that rare case, never
   * a broken or silently-omitted button. */
  onReanalyze: (() => void) | null;
}) {
  const { summary } = result;
  // FA-017.4 Part 13: full success keeps History as the trust-reinforcing
  // primary action (unchanged from FA-017.1 §20); a partial or fully
  // failed batch instead promotes "Analizar de nuevo" to primary -- the
  // most useful next step is seeing the folder's real current state, not
  // reading about what already failed.
  const isFullSuccess = summary.selected > 0 && summary.applied === summary.selected;

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

      {result.items.length > 0 ? (
        <div className="mt-3">
          <Collapsible triggerLabel="Ver detalles">
            <ul aria-label="Archivos procesados" className="flex flex-col gap-1">
              {result.items.map((item) => (
                <li key={item.policyDecisionId} className="text-sm text-foreground-muted">
                  <span className="font-medium text-foreground">{item.filename ?? "Archivo"}</span>
                  {" — "}
                  <span className="font-medium text-foreground">{item.message.title}</span>
                  {". "}
                  {item.message.detail}
                </li>
              ))}
            </ul>
          </Collapsible>
        </div>
      ) : null}

      <div className="mt-6 flex items-center gap-3">
        {isFullSuccess ? (
          <>
            <Button variant="primary" onClick={onViewHistory}>
              Ver historial
            </Button>
            {onReanalyze ? <Button onClick={onReanalyze}>Analizar de nuevo</Button> : null}
          </>
        ) : onReanalyze ? (
          <>
            <Button variant="primary" onClick={onReanalyze}>
              Analizar de nuevo
            </Button>
            <Button onClick={onViewHistory}>Ver historial</Button>
          </>
        ) : (
          <>
            <Button variant="primary" onClick={onDone}>
              Volver a la carpeta
            </Button>
            <Button onClick={onViewHistory}>Ver historial</Button>
          </>
        )}
        {isFullSuccess ? <Button onClick={onDone}>Volver a la carpeta</Button> : null}
        {!isFullSuccess && onReanalyze ? <Button onClick={onDone}>Volver a la carpeta</Button> : null}
      </div>
    </section>
  );
}
