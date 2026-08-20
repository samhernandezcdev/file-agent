import { useState } from "react";
import { RotateCcw } from "lucide-react";
import type { UndoOutcome } from "../../lib/outcomeMessages";
import { AlertDialog } from "../../components/ui/AlertDialog";
import { Banner } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";
import { Progress } from "../../components/ui/Progress";
import { Tooltip } from "../../components/ui/Tooltip";
import { formatHistoryDate } from "../../lib/formatDate";
import { guidanceForOutcome, undoCompletionPresentation } from "../../lib/outcomeMessages";
import { useManagedRootsQuery } from "../managed-roots/useManagedRoots";
import { useBatchDetailQuery, useUndoTransactionMutation } from "./useHistory";

/** FA-017.5 Part 10/11: the authoritative detail screen for one History
 * batch, reached only via the compact card's "Ver detalles". Always
 * fetches through useBatchDetailQuery(batchId) -- the backend's own
 * history.get_batch read model -- never treats the compact list row as
 * authoritative detail data. Undo lives exclusively here, per file (Part
 * 9/18): SUMMARY NAVIGATION != FILESYSTEM MUTATION. */
export function HistoryDetailScreen({
  batchId,
  onBack,
  onUndoCompleted,
}: {
  batchId: string;
  onBack: () => void;
  onUndoCompleted: (batchId: string, outcome: UndoOutcome) => void;
}) {
  const detailQuery = useBatchDetailQuery(batchId);
  const rootsQuery = useManagedRootsQuery();
  // Scopes the busy/duplicate-prevention state to the ONE transaction
  // currently being undone -- other items on the same screen remain
  // interactive (Part 20: disable THAT item's trigger, not the whole
  // screen).
  const [pendingTransactionId, setPendingTransactionId] = useState<string | null>(null);
  const undoMutation = useUndoTransactionMutation((transactionId, outcome) => {
    setPendingTransactionId(null);
    onUndoCompleted(batchId, { transactionId, result: outcome });
  });

  function handleUndo(transactionId: string) {
    setPendingTransactionId(transactionId);
    undoMutation.mutate(transactionId);
  }

  const backButton = (
    <button
      type="button"
      onClick={onBack}
      className="mb-3 text-sm font-medium text-primary hover:text-primary-hover"
    >
      ← Historial
    </button>
  );

  if (detailQuery.isLoading) {
    return (
      <section aria-labelledby="history-detail-heading">
        {backButton}
        <Progress label="Cargando…" />
      </section>
    );
  }
  if (detailQuery.data?.outcome !== "ok" || detailQuery.data.result.outcome !== "found") {
    return (
      <section aria-labelledby="history-detail-heading">
        {backButton}
        <Banner severity="error" title="No pudimos mostrar los detalles de esta operación." />
      </section>
    );
  }

  const entry = detailQuery.data.result;
  const rootName =
    entry.managedRootId !== null && rootsQuery.data?.outcome === "ok"
      ? rootsQuery.data.result.roots.find((root) => root.id === entry.managedRootId)?.displayPath
      : undefined;
  // Rejected/failed/unknown Undo guidance for whichever item's mutation
  // just settled -- routed through the same undoCompletionPresentation
  // classifier the retained-completion notice uses (Part 28), never a
  // raw UndoResultView.status check here. `undoMutation.variables` is
  // TanStack Query's own record of the transactionId the last mutate()
  // call used.
  const lastUndoPresentation =
    undoMutation.data && undoMutation.variables
      ? undoCompletionPresentation({ transactionId: undoMutation.variables, result: undoMutation.data })
      : null;
  const undoGuidance =
    lastUndoPresentation?.kind === "rejected"
      ? lastUndoPresentation.message
      : lastUndoPresentation?.kind === "unknown"
        ? guidanceForOutcome(undoMutation.data!, "undo_restore")
        : null;

  return (
    <section aria-labelledby="history-detail-heading">
      {backButton}
      <h1 id="history-detail-heading" className="mb-1 text-xl font-semibold text-foreground">
        {rootName ?? "Operación"}
      </h1>
      <p className="mb-3 text-sm text-foreground-subtle">{formatHistoryDate(entry.startedAt)}</p>

      <Banner
        severity={entry.summaryMessage.severity as "info" | "attention" | "error"}
        title={entry.summaryMessage.title}
        detail={entry.summaryMessage.detail}
      />

      {entry.recoveryMessage ? (
        <div className="mt-2">
          <Banner severity="info" title={entry.recoveryMessage.title} />
        </div>
      ) : null}

      {undoGuidance ? (
        <div className="mt-2">
          <Banner severity="error" title={undoGuidance.title} detail={undoGuidance.detail} />
        </div>
      ) : null}

      <ul aria-label="Archivos de esta operación" className="mt-4 flex flex-col gap-3">
        {(entry.items ?? []).map((item) => {
          const isPending = pendingTransactionId === item.transactionId && undoMutation.isPending;
          return (
            <li key={item.policyDecisionId} className="flex flex-col gap-0.5 border-b border-border pb-3">
              <div className="flex items-center justify-between gap-2">
                <Tooltip content={item.filename ?? "No pudimos identificar este archivo."}>
                  <span className="truncate text-sm font-medium text-foreground">
                    {item.filename ?? "No pudimos identificar este archivo."}
                  </span>
                </Tooltip>
                {item.undoAvailable && item.transactionId ? (
                  <AlertDialog
                    trigger={
                      <Button icon={<RotateCcw size={14} />} loading={isPending}>
                        {isPending ? "Deshaciendo…" : "Deshacer"}
                      </Button>
                    }
                    title="¿Deshacer este cambio?"
                    description="FileAgent intentará devolver el archivo a su ubicación original. No reemplazará archivos existentes."
                    cancelLabel="Cancelar"
                    confirmLabel="Sí, deshacer"
                    confirmVariant="primary"
                    onConfirm={() => handleUndo(item.transactionId as string)}
                  />
                ) : item.alreadyUndone ? (
                  <span className="text-sm text-foreground-subtle">Cambio deshecho</span>
                ) : null}
              </div>
              <span className="text-sm text-foreground-muted">{item.message.title}</span>
              {item.sourceDisplayPath && item.destinationDisplayPath ? (
                // Both durable paths present -- the full "source → destination"
                // fact is more useful here than item.message.detail's own
                // sentence (which already says the same thing in prose for
                // this exact case, e.g. "Se movió de X a Y") -- shown once,
                // never both.
                <Tooltip content={`${item.sourceDisplayPath} → ${item.destinationDisplayPath}`}>
                  <span className="truncate text-sm text-foreground-subtle">
                    {item.sourceDisplayPath} → {item.destinationDisplayPath}
                  </span>
                </Tooltip>
              ) : item.message.detail ? (
                <span className="text-sm text-foreground-subtle">{item.message.detail}</span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
