import type { LucideIcon } from "lucide-react";

/** Informational only -- no click handlers, no filtering (FA-017.1 §15).
 * A zero count stays visible in a visually quiet state rather than
 * disappearing, so "0 Necesitan atención" reads as good news. */
export function SummaryCard({
  icon: Icon,
  count,
  label,
  tone,
}: {
  icon: LucideIcon;
  count: number;
  label: string;
  tone: "ready" | "review" | "muted";
}) {
  const quiet = count === 0;
  const toneClass = quiet
    ? "text-foreground-subtle"
    : tone === "ready"
      ? "text-ready"
      : tone === "review"
        ? "text-review"
        : "text-foreground-muted";
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
      <Icon size={16} className={toneClass} aria-hidden="true" />
      <span className={`text-base font-semibold ${quiet ? "text-foreground-subtle" : "text-foreground"}`}>
        {count}
      </span>
      <span className="text-sm text-foreground-muted">{label}</span>
    </div>
  );
}
