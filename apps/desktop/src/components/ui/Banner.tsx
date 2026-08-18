export type BannerSeverity = "info" | "attention" | "error";

/** Status is never communicated by color alone -- a text label always
 * accompanies the severity styling. */
const LABEL_BY_SEVERITY: Record<BannerSeverity, string> = {
  info: "Información",
  attention: "Atención",
  error: "Error",
};

export function Banner({
  severity,
  title,
  detail,
}: {
  severity: BannerSeverity;
  title: string;
  detail?: string;
}) {
  return (
    <div className={`fa-banner fa-banner-${severity}`} role="status">
      <span className="fa-banner-label">{LABEL_BY_SEVERITY[severity]}:</span>{" "}
      <strong>{title}</strong>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}
