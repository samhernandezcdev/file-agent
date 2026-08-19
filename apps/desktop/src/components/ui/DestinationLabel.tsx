export function DestinationLabel({ label }: { label: string | null }) {
  if (label === null) return null;
  return <span className="text-sm text-foreground-muted">{label}</span>;
}
