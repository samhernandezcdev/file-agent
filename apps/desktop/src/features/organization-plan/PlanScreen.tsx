import { useEffect, useMemo, useState } from "react";
import type {
  BatchApplyResultView,
  ManagedRootUnavailableResultView,
  PlanAttentionView,
  PlanItemView,
} from "@file-agent/desktop-types";
import { CheckCircle2 } from "lucide-react";
import { Banner } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";
import { Checkbox } from "../../components/ui/Checkbox";
import { Collapsible } from "../../components/ui/Collapsible";
import { DestinationLabel } from "../../components/ui/DestinationLabel";
import { EmptyState } from "../../components/ui/EmptyState";
import { FileRow } from "../../components/ui/FileRow";
import { Progress } from "../../components/ui/Progress";
import { SectionHeader } from "../../components/ui/SectionHeader";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { Tooltip } from "../../components/ui/Tooltip";
import type { RustOutcome } from "../../desktop";
import { guidanceForOutcome } from "../../lib/outcomeMessages";
import { AnalysisSummary } from "./AnalysisSummary";
import { ConflictSummary } from "./ConflictSummary";
import {
  useAnalysisQuery,
  useApplyItemsMutation,
  usePlanQuery,
  useReviewMutations,
} from "./usePlanFlow";

type ApplyOutcome = RustOutcome<BatchApplyResultView | ManagedRootUnavailableResultView>;

function groupByCategory(items: readonly PlanItemView[]): [string, PlanItemView[]][] {
  const groups = new Map<string, PlanItemView[]>();
  for (const item of items) {
    const group = groups.get(item.categoryLabel);
    if (group) group.push(item);
    else groups.set(item.categoryLabel, [item]);
  }
  return [...groups.entries()];
}

export function PlanScreen({
  managedRootId,
  onApplyCompleted,
  onApplyPendingChange,
}: {
  managedRootId: string;
  onApplyCompleted: (managedRootId: string, outcome: ApplyOutcome) => void;
  onApplyPendingChange: (pending: boolean) => void;
}) {
  const analysisQuery = useAnalysisQuery(managedRootId);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const policyDecisionIds = useMemo(() => {
    if (analysisQuery.data?.outcome !== "ok" || analysisQuery.data.result.outcome !== "ok") {
      return [];
    }
    return analysisQuery.data.result.items.map((item) => item.policyDecisionId);
  }, [analysisQuery.data]);

  const planQuery = usePlanQuery(policyDecisionIds);
  const { approve, skip } = useReviewMutations(policyDecisionIds);
  const applyItems = useApplyItemsMutation((outcome) => onApplyCompleted(managedRootId, outcome));

  useEffect(() => {
    onApplyPendingChange(applyItems.isPending);
  }, [applyItems.isPending, onApplyPendingChange]);

  if (analysisQuery.isLoading) {
    return <Progress label="Analizando…" />;
  }
  if (analysisQuery.isError) {
    return <Banner severity="error" title="No pudimos analizar esta carpeta en este momento." />;
  }
  if (analysisQuery.data?.outcome !== "ok") {
    const guidance = analysisQuery.data ? guidanceForOutcome(analysisQuery.data, "managed_root") : null;
    return guidance ? <Banner severity="error" title={guidance.title} detail={guidance.detail} /> : null;
  }
  if (analysisQuery.data.result.outcome === "managed_root_unavailable") {
    const message = analysisQuery.data.result.message;
    return <Banner severity="error" title={message.title} detail={message.detail} />;
  }

  const analysis = analysisQuery.data.result;

  if (analysis.items.length === 0) {
    return (
      <EmptyState
        icon={CheckCircle2}
        title="No encontramos archivos nuevos para organizar"
        detail="Esta carpeta ya está al día."
      />
    );
  }

  function toggle(actionId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(actionId)) next.delete(actionId);
      else next.add(actionId);
      return next;
    });
  }

  const planItems: PlanItemView[] =
    planQuery.data?.outcome === "ok" && planQuery.data.result.outcome === "ok"
      ? planQuery.data.result.items
      : [];
  const attentions: PlanAttentionView[] =
    planQuery.data?.outcome === "ok" && planQuery.data.result.outcome === "ok"
      ? planQuery.data.result.attentions
      : [];
  const attentionsByCategory = new Map<string, PlanAttentionView[]>();
  for (const attention of attentions) {
    const list = attentionsByCategory.get(attention.categoryLabel);
    if (list) list.push(attention);
    else attentionsByCategory.set(attention.categoryLabel, [attention]);
  }

  const selectableIds = planItems.filter((item) => item.selectable).map((item) => item.actionId);
  const selectedSelectableCount = selectableIds.filter((id) => selected.has(id)).length;
  const allSelectableSelected = selectableIds.length > 0 && selectedSelectableCount === selectableIds.length;

  function toggleSelectAll(checked: boolean) {
    setSelected(checked ? new Set(selectableIds) : new Set());
  }

  const applyGuidance = applyItems.data ? guidanceForOutcome(applyItems.data, "apply") : null;

  function handleApply() {
    const ids = [...selected];
    // Synchronous: `selected` becomes empty in THIS render, so the
    // "Organizar" button below is disabled before any second click could
    // ever be processed -- the backend FIFO remains the real safety net.
    setSelected(new Set());
    applyItems.mutate(ids);
  }

  return (
    <section aria-labelledby="plan-heading">
      <h1 id="plan-heading" className="mb-3 text-xl font-semibold text-foreground">
        Vista previa de organización
      </h1>

      {analysis.protectedTreesMessage ? (
        <Banner
          severity="info"
          title={analysis.protectedTreesMessage.title}
          detail={analysis.protectedTreesMessage.detail}
        />
      ) : null}

      <AnalysisSummary
        summary={
          planQuery.data?.outcome === "ok" && planQuery.data.result.outcome === "ok"
            ? planQuery.data.result.summary
            : {
                filesTotal: analysis.items.length,
                ready: 0,
                reviewRequired: 0,
                conflicts: 0,
                invalid: 0,
                blocked: 0,
                skipped: 0,
                noAction: 0,
                protected: 0,
                issues: 0,
              }
        }
      />

      {selectableIds.length > 0 ? (
        <div className="mb-2 flex items-center gap-2">
          <Checkbox
            checked={allSelectableSelected ? true : selectedSelectableCount > 0 ? "indeterminate" : false}
            onCheckedChange={toggleSelectAll}
            label="Seleccionar todos los listos"
          />
          <span className="text-sm text-foreground-muted">Seleccionar todos los listos</span>
        </div>
      ) : null}

      <div aria-label="Archivos analizados">
        {groupByCategory(planItems).map(([categoryLabel, items]) => (
          <div key={categoryLabel}>
            <SectionHeader>
              {categoryLabel} · {items.length}
            </SectionHeader>

            {(attentionsByCategory.get(categoryLabel) ?? []).map((attention) => (
              <ConflictSummary
                key={attention.destinationLabel}
                attention={attention}
                onReanalyze={() => analysisQuery.refetch()}
              />
            ))}

            {items.map((item) => (
              <FileRow
                key={item.actionId}
                leading={
                  item.selectable ? (
                    <Checkbox
                      checked={selected.has(item.actionId)}
                      onCheckedChange={() => toggle(item.actionId)}
                      label={`Seleccionar ${item.filename}`}
                    />
                  ) : (
                    <span className="w-4" />
                  )
                }
                primary={
                  <Tooltip content={item.filename}>
                    <span>{item.filename}</span>
                  </Tooltip>
                }
                trailing={
                  <div className="flex items-center gap-3">
                    <StatusBadge status={item.status} label={item.title} />
                    {item.status === "review_required" ? (
                      <>
                        <Button onClick={() => approve.mutate(item.actionId)} disabled={approve.isPending}>
                          Aprobar
                        </Button>
                        <Button onClick={() => skip.mutate(item.actionId)} disabled={skip.isPending}>
                          Omitir
                        </Button>
                      </>
                    ) : null}
                    <Collapsible triggerLabel="Ver ubicación">
                      <p className="text-xs text-foreground-subtle">Origen: {item.sourceDisplayPath}</p>
                      {item.destinationDisplayPath ? (
                        <DestinationLabel label={`Destino: ${item.destinationDisplayPath}`} />
                      ) : null}
                    </Collapsible>
                  </div>
                }
              />
            ))}
          </div>
        ))}
      </div>

      {applyGuidance ? (
        <div className="mt-4">
          <Banner severity="error" title={applyGuidance.title} detail={applyGuidance.detail} />
        </div>
      ) : null}

      <div className="mt-6 border-t border-border pt-4">
        {selected.size > 0 ? (
          <p className="mb-2 text-sm text-foreground-muted">
            {selected.size} archivo{selected.size === 1 ? "" : "s"} se moverá
            {selected.size === 1 ? "" : "n"} · 0 archivos se eliminarán · Puedes deshacer los cambios
          </p>
        ) : null}
        <Button
          variant="primary"
          onClick={handleApply}
          disabled={selected.size === 0 || applyItems.isPending}
        >
          Organizar {selected.size} archivo{selected.size === 1 ? "" : "s"}
        </Button>
        {applyItems.isPending ? (
          <div className="mt-2">
            <Progress label="Organizando…" />
          </div>
        ) : null}
      </div>
    </section>
  );
}
