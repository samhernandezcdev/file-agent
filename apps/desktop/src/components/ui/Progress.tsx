import { Loader2 } from "lucide-react";

/** Indeterminate only -- FA-017.1 ships no granular "N de M" progress
 * (Rust discards apply.items' progress frames today; faking a count would
 * violate the "never fabricate certainty" principle, §1/§19). */
export function Progress({ label }: { label: string }) {
  return (
    <p role="status" className="flex items-center gap-2 text-sm text-foreground-muted">
      <Loader2 size={16} className="animate-spin text-primary" aria-hidden="true" />
      {label}
    </p>
  );
}
