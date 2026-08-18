import { useMemo, useState } from "react";
import type { BatchApplyResultView } from "@file-agent/desktop-types";
import { Banner } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";
import { guidanceForOutcome } from "../../lib/outcomeMessages";
import {
  useAnalysisQuery,
  useApplyItemsMutation,
  usePlanQuery,
  useReviewMutations,
} from "./usePlanFlow";

export function PlanScreen({
  managedRootId,
  onApplied,
}: {
  managedRootId: string;
  onApplied: (result: BatchApplyResultView) => void;
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
  const applyItems = useApplyItemsMutation();

  if (analysisQuery.isLoading) {
    return <p role="status">Analizando…</p>;
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
    return <p>No encontramos archivos nuevos para organizar en esta carpeta.</p>;
  }

  function toggle(actionId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(actionId)) next.delete(actionId);
      else next.add(actionId);
      return next;
    });
  }

  const planItems =
    planQuery.data?.outcome === "ok" && planQuery.data.result.outcome === "ok"
      ? planQuery.data.result.items
      : [];

  const applyGuidance = applyItems.data ? guidanceForOutcome(applyItems.data, "apply") : null;

  function handleApply() {
    const ids = [...selected];
    // Synchronous: `selected` becomes empty in THIS render, so the
    // "Organizar" button below is disabled before any second click could
    // ever be processed -- the backend FIFO remains the real safety net.
    setSelected(new Set());
    applyItems.mutate(ids, {
      onSuccess: (outcome) => {
        if (outcome.outcome === "ok" && outcome.result.outcome === "ok") {
          onApplied(outcome.result);
        }
      },
    });
  }

  return (
    <section aria-labelledby="plan-heading">
      <h1 id="plan-heading">Vista previa de organización</h1>

      {analysis.protectedTreesMessage ? (
        <Banner
          severity="info"
          title={analysis.protectedTreesMessage.title}
          detail={analysis.protectedTreesMessage.detail}
        />
      ) : null}

      <ul aria-label="Archivos analizados">
        {planItems.map((item) => (
          <li key={item.actionId}>
            {item.selectable ? (
              <label>
                <input
                  type="checkbox"
                  checked={selected.has(item.actionId)}
                  onChange={() => toggle(item.actionId)}
                />
                {item.filename}
              </label>
            ) : (
              <span>{item.filename}</span>
            )}
            <span> — {item.title}</span>
            {item.status === "review_required" ? (
              <span>
                <Button onClick={() => approve.mutate(item.actionId)} disabled={approve.isPending}>
                  Aprobar
                </Button>
                <Button onClick={() => skip.mutate(item.actionId)} disabled={skip.isPending}>
                  Omitir
                </Button>
              </span>
            ) : null}
          </li>
        ))}
      </ul>

      {applyGuidance ? (
        <Banner severity="error" title={applyGuidance.title} detail={applyGuidance.detail} />
      ) : null}

      <Button
        variant="primary"
        onClick={handleApply}
        disabled={selected.size === 0 || applyItems.isPending}
      >
        Organizar
      </Button>
      {applyItems.isPending ? <p role="status">Organizando…</p> : null}
    </section>
  );
}
