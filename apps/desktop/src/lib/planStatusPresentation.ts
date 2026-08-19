import {
  AlertCircle,
  CheckCircle2,
  FolderX,
  HelpCircle,
  Info,
  MinusCircle,
  Shield,
  ShieldAlert,
  type LucideIcon,
} from "lucide-react";

/** FA-017.1 §14: icon + color-bucket selection keyed off the backend's own
 * PlanItemView.status string -- presentation glue only. The rendered TEXT
 * always comes from the DTO's own title/detail (never invented here); this
 * only picks which icon/token-color accompanies text that already exists,
 * exactly the approved §10/§14 table. Never used to derive selectable,
 * authorization, or any behavior. */
export type StatusBucket = "ready" | "review" | "conflict" | "protected" | "muted";

const ICON_BY_STATUS: Record<string, LucideIcon> = {
  ready: CheckCircle2,
  review_required: AlertCircle,
  conflict: FolderX,
  invalid: HelpCircle,
  protected: Shield,
  blocked: ShieldAlert,
  skipped: MinusCircle,
  no_action: Info,
};

const BUCKET_BY_STATUS: Record<string, StatusBucket> = {
  ready: "ready",
  review_required: "review",
  conflict: "conflict",
  invalid: "conflict",
  protected: "protected",
  blocked: "protected",
  skipped: "muted",
  no_action: "muted",
};

export function statusIcon(status: string): LucideIcon {
  return ICON_BY_STATUS[status] ?? Info;
}

export function statusBucket(status: string): StatusBucket {
  return BUCKET_BY_STATUS[status] ?? "muted";
}
