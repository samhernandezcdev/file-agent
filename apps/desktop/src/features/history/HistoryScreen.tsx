import type { BatchHistoryEntryView } from "@file-agent/desktop-types";
import { History } from "lucide-react";
import { Banner } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { formatHistoryDate } from "../../lib/formatDate";
import { useManagedRootsQuery } from "../managed-roots/useManagedRoots";
import { useRecentHistoryQuery } from "./useHistory";

/** FA-017.5 Part 6/7/9: a compact, summary-only operation card -- SUMMARY
 * FIRST, DETAIL ON DEMAND. Never renders file rows, full paths, per-file
 * reasons, transaction ids, UUIDs, raw statuses, or any undo/recovery
 * mutation trigger (SUMMARY NAVIGATION != FILESYSTEM MUTATION, Part 9) --
 * "Ver detalles" is the sole action, always primary since nothing
 * competes with it. Renders `recoveryMessage` opaquely: it never derives
 * AVAILABLE/MIXED/FULLY_RECOVERED meaning itself (Part 31). */
function HistoryOperationCard({
  row,
  rootName,
  onOpenBatch,
}: {
  row: BatchHistoryEntryView;
  rootName: string | undefined;
  onOpenBatch: (batchId: string) => void;
}) {
  return (
    <Card className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-3">
        <span className="truncate text-base font-semibold text-foreground">
          {rootName ?? "Operación"}
        </span>
        <span className="shrink-0 text-sm text-foreground-subtle">
          {formatHistoryDate(row.startedAt)}
        </span>
      </div>
      <div>
        <p className="text-sm font-medium text-foreground">{row.summaryMessage.title}</p>
        {row.summaryMessage.detail ? (
          <p className="text-sm text-foreground-muted">{row.summaryMessage.detail}</p>
        ) : null}
      </div>
      {row.recoveryMessage ? (
        <p className="text-sm text-foreground-muted">{row.recoveryMessage.title}</p>
      ) : null}
      <div className="mt-1 flex justify-end">
        <Button variant="primary" onClick={() => onOpenBatch(row.batchId)}>
          Ver detalles
        </Button>
      </div>
    </Card>
  );
}

export function HistoryScreen({
  onOpenBatch,
  onChooseAnotherFolder,
}: {
  onOpenBatch: (batchId: string) => void;
  onChooseAnotherFolder: () => void;
}) {
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
        <EmptyState
          icon={History}
          title="Aún no hay actividad"
          detail="Cuando organices archivos, podrás revisar aquí los cambios realizados."
          action={
            <Button variant="primary" onClick={onChooseAnotherFolder}>
              Elegir otra carpeta
            </Button>
          }
        />
      ) : (
        <ul aria-label="Operaciones recientes" className="flex flex-col gap-3">
          {rows.map((row) => (
            <li key={row.batchId}>
              {row.rowType === "entry" ? (
                <HistoryOperationCard
                  row={row}
                  rootName={row.managedRootId ? rootNameById.get(row.managedRootId) : undefined}
                  onOpenBatch={onOpenBatch}
                />
              ) : (
                <Card>
                  <Banner severity="error" title={row.message.title} detail={row.message.detail} />
                </Card>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
