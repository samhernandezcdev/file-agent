import { AlertTriangle, Info, XCircle, type LucideIcon } from "lucide-react";

export type BannerSeverity = "info" | "attention" | "error";

/** Status is never communicated by color alone -- a text label and an
 * icon always accompany the severity styling (FA-017.1 §4). */
const LABEL_BY_SEVERITY: Record<BannerSeverity, string> = {
  info: "Información",
  attention: "Atención",
  error: "Error",
};

const ICON_BY_SEVERITY: Record<BannerSeverity, LucideIcon> = {
  info: Info,
  attention: AlertTriangle,
  error: XCircle,
};

const BORDER_CLASS_BY_SEVERITY: Record<BannerSeverity, string> = {
  info: "border-l-info",
  attention: "border-l-warning",
  error: "border-l-danger",
};

const ICON_CLASS_BY_SEVERITY: Record<BannerSeverity, string> = {
  info: "text-info",
  attention: "text-warning",
  error: "text-danger",
};

export function Banner({
  severity,
  title,
  detail,
  action,
}: {
  severity: BannerSeverity;
  title: string;
  detail?: string;
  action?: React.ReactNode;
}) {
  const Icon = ICON_BY_SEVERITY[severity];
  return (
    <div
      role="status"
      className={`flex gap-2 rounded-md border-l-4 bg-surface-muted px-3 py-2.5 ${BORDER_CLASS_BY_SEVERITY[severity]}`}
    >
      <Icon size={16} className={`mt-0.5 shrink-0 ${ICON_CLASS_BY_SEVERITY[severity]}`} aria-hidden="true" />
      <div className="flex-1">
        <span className="sr-only">{LABEL_BY_SEVERITY[severity]}: </span>
        <strong className="text-sm font-medium text-foreground">{title}</strong>
        {detail ? <p className="mt-0.5 text-sm text-foreground-muted">{detail}</p> : null}
        {action ? <div className="mt-2">{action}</div> : null}
      </div>
    </div>
  );
}
