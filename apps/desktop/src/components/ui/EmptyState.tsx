import type { LucideIcon } from "lucide-react";

/** Every empty state answers: what happened, is it a problem, what to do
 * now (FA-017.1 §1/§22). Never a bare one-line <p>. */
export function EmptyState({
  icon: Icon,
  title,
  detail,
  action,
}: {
  icon: LucideIcon;
  title: string;
  detail?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border py-12 text-center">
      <Icon size={32} className="text-foreground-subtle" aria-hidden="true" />
      <p className="text-base font-semibold text-foreground">{title}</p>
      {detail ? <div className="max-w-sm text-sm text-foreground-muted">{detail}</div> : null}
      {action}
    </div>
  );
}
