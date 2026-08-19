import { FolderKanban, History } from "lucide-react";

export type SidebarDestination = "carpetas" | "historial";

/** Narrow, persistent, fixed-width -- no collapse, no filesystem tree, no
 * Settings entry point (FA-017.1 §4). Active state is background + left
 * accent bar + semibold text together, never color alone. */
export function Sidebar({
  active,
  onNavigate,
}: {
  active: SidebarDestination;
  onNavigate: (destination: SidebarDestination) => void;
}) {
  return (
    <nav aria-label="Navegación principal" className="flex w-[200px] shrink-0 flex-col gap-1 border-r border-border bg-surface p-3">
      <div className="mb-4 flex items-center gap-2 px-2 text-sm font-semibold text-foreground">
        <FolderKanban size={18} className="text-primary" aria-hidden="true" />
        FileAgent
      </div>
      <NavItem
        icon={FolderKanban}
        label="Carpetas"
        active={active === "carpetas"}
        onClick={() => onNavigate("carpetas")}
      />
      <NavItem
        icon={History}
        label="Historial"
        active={active === "historial"}
        onClick={() => onNavigate("historial")}
      />
    </nav>
  );
}

function NavItem({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: typeof FolderKanban;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={
        active
          ? "flex items-center gap-2 rounded-md border-l-4 border-primary bg-surface-elevated px-2 py-2 text-sm font-semibold text-foreground"
          : "flex items-center gap-2 rounded-md border-l-4 border-transparent px-2 py-2 text-sm font-medium text-foreground-muted hover:bg-surface-muted"
      }
    >
      <Icon size={16} aria-hidden="true" />
      {label}
    </button>
  );
}
