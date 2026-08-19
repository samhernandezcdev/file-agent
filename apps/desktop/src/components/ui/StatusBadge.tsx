import { statusBucket, statusIcon, type StatusBucket } from "../../lib/planStatusPresentation";

/** Icon + text always together -- status is never communicated by color
 * alone (FA-017.1 §4/§10/§14). `label` is always backend-composed text
 * (PlanItemView.title, etc.); this component never invents copy. */
const TEXT_CLASS_BY_BUCKET: Record<StatusBucket, string> = {
  ready: "text-ready",
  review: "text-review",
  conflict: "text-conflict",
  protected: "text-protected",
  muted: "text-foreground-muted",
};

export function StatusBadge({ status, label }: { status: string; label: string }) {
  const Icon = statusIcon(status);
  const bucket = statusBucket(status);
  return (
    <span className={`inline-flex items-center gap-1 text-sm font-medium ${TEXT_CLASS_BY_BUCKET[bucket]}`}>
      <Icon size={14} aria-hidden="true" />
      {label}
    </span>
  );
}
