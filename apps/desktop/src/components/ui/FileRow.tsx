/** Generic scannable row shell -- ~40-44px tall (FA-017.1 §12). Carries no
 * product knowledge; feature components supply every slot's content. */
export function FileRow({
  leading,
  primary,
  secondary,
  trailing,
}: {
  leading?: React.ReactNode;
  primary: React.ReactNode;
  secondary?: React.ReactNode;
  trailing?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-11 flex-wrap items-center gap-3 border-b border-border py-2">
      {leading}
      <span className="min-w-0 flex-1 truncate text-sm text-foreground">{primary}</span>
      {secondary}
      <span className="shrink-0">{trailing}</span>
    </div>
  );
}
