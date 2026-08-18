import type { BatchApplyResultView } from "@file-agent/desktop-types";
import { Banner } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";

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
  return (
    <section aria-labelledby="apply-results-heading">
      <h1 id="apply-results-heading">Resultado</h1>
      <Banner
        severity={result.summaryMessage.severity as "info" | "attention" | "error"}
        title={result.summaryMessage.title}
        detail={result.summaryMessage.detail}
      />
      <p>
        {summary.applied} de {summary.selected} archivos se organizaron
      </p>
      <ul aria-label="Archivos procesados">
        {result.items.map((item) => (
          <li key={item.policyDecisionId}>
            <span>{item.filename ?? "Archivo"}</span>
            <span> — {item.message.title}</span>
          </li>
        ))}
      </ul>
      <Button variant="primary" onClick={onViewHistory}>
        Ver en historial
      </Button>
      <Button onClick={onDone}>Listo</Button>
    </section>
  );
}
