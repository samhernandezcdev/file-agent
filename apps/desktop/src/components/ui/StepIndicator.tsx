import { Check, Loader2 } from "lucide-react";

/** Pure, non-interactive progress readout -- zero click/onSelect handlers
 * of any kind (FA-017.1 §5a). "Organizar" is not a step; it is Revisar's
 * primary CTA. */
export type StepState = "done" | "current" | "pending" | "upcoming";

const STEPS: readonly { key: "carpeta" | "revisar" | "resultado"; label: string }[] = [
  { key: "carpeta", label: "Carpeta" },
  { key: "revisar", label: "Revisar" },
  { key: "resultado", label: "Resultado" },
];

function StepGlyph({ state }: { state: StepState }) {
  if (state === "done") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
        <Check size={12} />
      </span>
    );
  }
  if (state === "pending") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full border-2 border-primary text-primary">
        <Loader2 size={12} className="animate-spin" />
      </span>
    );
  }
  if (state === "current") {
    return <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary" />;
  }
  return <span className="flex h-5 w-5 items-center justify-center rounded-full border-2 border-border" />;
}

export function StepIndicator({ states }: { states: Record<"carpeta" | "revisar" | "resultado", StepState> }) {
  return (
    <ol aria-hidden="true" className="flex items-center gap-2">
      {STEPS.map((step, i) => (
        <li key={step.key} className="flex items-center gap-2">
          <span className="flex items-center gap-1.5">
            <StepGlyph state={states[step.key]} />
            <span
              className={
                states[step.key] === "upcoming"
                  ? "text-sm text-foreground-subtle"
                  : "text-sm font-medium text-foreground"
              }
            >
              {step.label}
            </span>
          </span>
          {i < STEPS.length - 1 ? <span className="h-px w-6 bg-border" /> : null}
        </li>
      ))}
    </ol>
  );
}
