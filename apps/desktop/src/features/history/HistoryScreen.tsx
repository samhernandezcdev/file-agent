import { useState } from "react";
import type { BatchHistoryEntryView } from "@file-agent/desktop-types";
import { History, RotateCcw } from "lucide-react";
import { AlertDialog } from "../../components/ui/AlertDialog";
import { Banner } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { formatHistoryDate } from "../../lib/formatDate";
import { guidanceForOutcome } from "../../lib/outcomeMessages";
import { useManagedRootsQuery } from "../managed-roots/useManagedRoots";
import { useBatchDetailQuery, useRecentHistoryQuery, useUndoTransactionMutation } from "./useHistory";

function BatchDetail({ batchId }: { batchId: string }) {
  const detailQuery = useBatchDetailQuery(batchId);
  const undoMutation = useUndoTransactionMutation();

  if (detailQuery.isLoading) return <p role="status">Cargando…</p>;
  if (detailQuery.data?.outcome !== "ok" || detailQuery.data.result.outcome !== "found") {
    return <Banner severity="error" title="No pudimos mostrar los detalles de esta operación." />;
  }

  const entry = detailQuery.data.result;
  const undoGuidance = undoMutation.data ? guidanceForOutcome(undoMutation.data, "undo_restore") : null;

  return (
    <div aria-label="Detalle de la operación" className="mt-3 border-t border-border pt-3">
      <Banner
        severity={entry.summaryMessage.severity as "info" | "attention" | "error"}
        title={entry.summaryMessage.title}
        detail={entry.summaryMessage.detail}
      />
      {undoGuidance ? (
        <div className="mt-2">
          <Banner severity="error" title={undoGuidance.title} detail={undoGuidance.detail} />
        </div>
      ) : null}
      <ul className="mt-2 flex flex-col gap-1">
        {(entry.items ?? []).map((item) => (
          <li key={item.policyDecisionId} className="flex items-center justify-between py-1 text-sm">
            <span className="text-foreground-muted">{item.status}</span>
            {item.status === "applied" && item.transactionId ? (
              <AlertDialog
                trigger={<Button icon={<RotateCcw size={14} />}>Deshacer</Button>}
                title="¿Deshacer este cambio?"
                description="El archivo volverá a su carpeta original."
                cancelLabel="Cancelar"
                confirmLabel="Sí, deshacer"
                confirmVariant="danger"
                onConfirm={() => undoMutation.mutate(item.transactionId as string)}
              />
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function HistoryEntryRow({ row, rootName }: { row: BatchHistoryEntryView; rootName: string | undefined }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-border py-2">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full flex-col items-start gap-0.5 text-left"
      >
        <span className="text-xs text-foreground-subtle">{formatHistoryDate(row.startedAt)}</span>
        <span className="text-sm font-medium text-foreground">{row.summaryMessage.title}</span>
        {rootName ? <span className="text-xs text-foreground-muted">{rootName}</span> : null}
      </button>
      {open ? <BatchDetail batchId={row.batchId} /> : null}
    </li>
  );
}

export function HistoryScreen() {
  const recentQuery = useRecentHistoryQuery();
  const rootsQuery = useManagedRootsQuery();

  if (recentQuery.isLoading) return <p role="status">Cargando historial…</p>;
  if (recentQuery.data?.outcome !== "ok") {
    return <Banner severity="error" title="No pudimos cargar el historial en este momento." />;
  }

  const rows = recentQuery.data.result.rows;
  const rootNameById = new Map<string, string>();
  if (rootsQuery.data?.outcome === "ok") {
    for (const root of rootsQuery.data.result.roots) rootNameById.set(root.id, root.displayPath);
  }

  return (
    <section aria-labelledby="history-heading">
      <h1 id="history-heading" className="mb-3 text-xl font-semibold text-foreground">
        Historial
      </h1>
      {rows.length === 0 ? (
        <EmptyState icon={History} title="Todavía no organizaste ningún archivo" />
      ) : (
        <ul aria-label="Operaciones recientes" className="flex flex-col">
          {rows.map((row) =>
            row.rowType === "entry" ? (
              <HistoryEntryRow
                key={row.batchId}
                row={row}
                rootName={row.managedRootId ? rootNameById.get(row.managedRootId) : undefined}
              />
            ) : (
              <li key={row.batchId} className="border-b border-border py-2">
                <Banner severity="error" title={row.message.title} detail={row.message.detail} />
              </li>
            ),
          )}
        </ul>
      )}
    </section>
  );
}
