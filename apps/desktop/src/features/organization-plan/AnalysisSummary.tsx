import type { PlanSummaryView } from "@file-agent/desktop-types";
import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { SummaryCard } from "../../components/ui/SummaryCard";

/** One total line + exactly three informational SummaryCards (FA-017.1
 * §15) -- no filtering, no click handlers. The total is not a fourth
 * card. */
export function AnalysisSummary({ summary }: { summary: PlanSummaryView }) {
  const noSeMoveran =
    summary.conflicts +
    summary.invalid +
    summary.blocked +
    summary.skipped +
    summary.noAction +
    summary.protected;

  return (
    <div className="mb-4">
      <p className="mb-2 text-sm text-foreground-muted">
        {summary.filesTotal} archivo{summary.filesTotal === 1 ? "" : "s"} encontrado
        {summary.filesTotal === 1 ? "" : "s"}
      </p>
      <div className="flex flex-wrap gap-2">
        <SummaryCard icon={CheckCircle2} count={summary.ready} label="Listos" tone="ready" />
        <SummaryCard
          icon={AlertTriangle}
          count={summary.reviewRequired}
          label="Necesitan atención"
          tone="review"
        />
        <SummaryCard icon={Info} count={noSeMoveran} label="No se moverán" tone="muted" />
      </div>
    </div>
  );
}
