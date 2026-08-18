import { useState } from "react";
import { Banner } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";
import { guidanceForOutcome } from "../../lib/outcomeMessages";
import { useBatchDetailQuery, useRecentHistoryQuery, useUndoTransactionMutation } from "./useHistory";

function BatchDetail({ batchId }: { batchId: string }) {
  const detailQuery = useBatchDetailQuery(batchId);
  const undoMutation = useUndoTransactionMutation();
  const [confirmingTransactionId, setConfirmingTransactionId] = useState<string | null>(null);

  if (detailQuery.isLoading) return <p role="status">Cargando…</p>;
  if (detailQuery.data?.outcome !== "ok" || detailQuery.data.result.outcome !== "found") {
    return <Banner severity="error" title="No pudimos mostrar los detalles de esta operación." />;
  }

  const entry = detailQuery.data.result;
  const undoGuidance = undoMutation.data ? guidanceForOutcome(undoMutation.data, "undo_restore") : null;

  return (
    <div aria-label="Detalle de la operación">
      <Banner
        severity={entry.summaryMessage.severity as "info" | "attention" | "error"}
        title={entry.summaryMessage.title}
        detail={entry.summaryMessage.detail}
      />
      {undoGuidance ? <Banner severity="error" title={undoGuidance.title} detail={undoGuidance.detail} /> : null}
      <ul>
        {(entry.items ?? []).map((item) => (
          <li key={item.policyDecisionId}>
            <span>{item.status}</span>
            {item.status === "applied" && item.transactionId ? (
              confirmingTransactionId === item.transactionId ? (
                <span>
                  <span>¿Deshacer este cambio?</span>
                  <Button
                    variant="danger"
                    onClick={() => {
                      undoMutation.mutate(item.transactionId as string);
                      setConfirmingTransactionId(null);
                    }}
                  >
                    Sí, deshacer
                  </Button>
                  <Button onClick={() => setConfirmingTransactionId(null)}>Cancelar</Button>
                </span>
              ) : (
                <Button onClick={() => setConfirmingTransactionId(item.transactionId as string)}>
                  Deshacer
                </Button>
              )
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function HistoryScreen() {
  const recentQuery = useRecentHistoryQuery();
  const [openBatchId, setOpenBatchId] = useState<string | null>(null);

  if (recentQuery.isLoading) return <p role="status">Cargando historial…</p>;
  if (recentQuery.data?.outcome !== "ok") {
    return <Banner severity="error" title="No pudimos cargar el historial en este momento." />;
  }

  const rows = recentQuery.data.result.rows;

  return (
    <section aria-labelledby="history-heading">
      <h1 id="history-heading">Historial</h1>
      {rows.length === 0 ? <p>Todavía no organizaste ningún archivo.</p> : null}
      <ul aria-label="Operaciones recientes">
        {rows.map((row) =>
          row.rowType === "entry" ? (
            <li key={row.batchId}>
              <button type="button" onClick={() => setOpenBatchId(row.batchId)}>
                {row.summaryMessage.title}
              </button>
            </li>
          ) : (
            <li key={row.batchId}>
              <Banner severity="error" title={row.message.title} detail={row.message.detail} />
            </li>
          ),
        )}
      </ul>
      {openBatchId ? <BatchDetail batchId={openBatchId} /> : null}
    </section>
  );
}
