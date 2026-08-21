import { useState } from "react";
import { CheckCircle2, Eye, Folder, FolderPlus, Trash2 } from "lucide-react";
import { Banner } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { IconButton } from "../../components/ui/IconButton";
import { Tooltip } from "../../components/ui/Tooltip";
import { desktop } from "../../desktop";
import { guidanceForOutcome } from "../../lib/outcomeMessages";
import {
  useAddManagedRootMutation,
  useManagedRootsQuery,
  useRemoveManagedRootMutation,
} from "./useManagedRoots";

/** FA-017.6 Part 2: a static, non-interactive 3-stage workflow row --
 * never a tour, never clickable, no progress/step state. Purely
 * explanatory, rendered once as part of the first-run hero's `detail`. */
function WorkflowStage({ icon: Icon, label }: { icon: typeof FolderPlus; label: string }) {
  return (
    <div className="flex flex-1 flex-col items-center gap-1">
      <Icon size={24} className="text-foreground-muted" aria-hidden="true" />
      <span className="text-sm font-medium text-foreground">{label}</span>
    </div>
  );
}

/** One empty state, keyed only on managedRoots.length === 0 (FA-017.1
 * §22) -- no localStorage, no first-run/returning distinction anywhere in
 * the frontend, no onboarding persistence of any kind (FA-017.6 Part 5).
 * Serves a genuinely first-time user and a returning user with no roots
 * left equally well. */
function FirstRunEmptyState({ onAddFolder, busy }: { onAddFolder: () => void; busy: boolean }) {
  return (
    <EmptyState
      icon={FolderPlus}
      title="Organiza tus archivos sin perder el control"
      detail={
        <div className="flex flex-col items-center gap-6">
          <p className="text-base text-foreground-muted">
            Elige una carpeta. FileAgent analizará los archivos y te mostrará los cambios antes de
            organizar.
          </p>
          <div className="flex w-full items-start justify-center gap-4">
            <WorkflowStage icon={FolderPlus} label="Elige una carpeta" />
            <WorkflowStage icon={Eye} label="Revisa los cambios" />
            <WorkflowStage icon={CheckCircle2} label="Organiza" />
          </div>
          <ul className="flex flex-col gap-1 text-left text-sm text-foreground-muted">
            <li>✓ Revisa antes de organizar</li>
            <li>✓ No reemplazamos archivos existentes</li>
            <li>✓ Puedes deshacer cambios</li>
          </ul>
        </div>
      }
      action={
        <Button variant="primary" onClick={onAddFolder} disabled={busy}>
          Elegir carpeta
        </Button>
      }
    />
  );
}

export function ManagedRootsScreen({
  onAnalyze,
}: {
  onAnalyze: (managedRootId: string) => void;
}) {
  const rootsQuery = useManagedRootsQuery();
  const addMutation = useAddManagedRootMutation();
  const removeMutation = useRemoveManagedRootMutation();
  const [pickerBusy, setPickerBusy] = useState(false);

  async function handleAddFolder() {
    setPickerBusy(true);
    try {
      const path = await desktop.pickFolder();
      if (path === null) return; // canceled picker performs no registration
      addMutation.mutate(path);
    } finally {
      setPickerBusy(false);
    }
  }

  const addGuidance = addMutation.data ? guidanceForOutcome(addMutation.data, "managed_root") : null;
  const removeGuidance = removeMutation.data
    ? guidanceForOutcome(removeMutation.data, "managed_root")
    : null;

  const roots = rootsQuery.data?.outcome === "ok" ? rootsQuery.data.result.roots : null;

  return (
    <section aria-labelledby="managed-roots-heading">
      <h1 id="managed-roots-heading" className="mb-3 text-xl font-semibold text-foreground">
        Carpetas que FileAgent puede organizar
      </h1>

      {roots !== null && roots.length > 0 ? (
        <div className="mb-4">
          <Button
            variant="primary"
            icon={<FolderPlus size={14} />}
            onClick={handleAddFolder}
            disabled={pickerBusy || addMutation.isPending}
          >
            Agregar carpeta
          </Button>
        </div>
      ) : null}

      {addGuidance ? <Banner severity="error" title={addGuidance.title} detail={addGuidance.detail} /> : null}
      {removeGuidance ? (
        <Banner severity="error" title={removeGuidance.title} detail={removeGuidance.detail} />
      ) : null}

      {rootsQuery.isLoading ? <p role="status">Cargando carpetas…</p> : null}
      {rootsQuery.isError ? (
        <Banner severity="error" title="No pudimos cargar tus carpetas en este momento." />
      ) : null}

      {roots !== null ? (
        roots.length === 0 ? (
          <FirstRunEmptyState onAddFolder={handleAddFolder} busy={pickerBusy || addMutation.isPending} />
        ) : (
          <ul aria-label="Carpetas administradas" className="flex flex-col gap-2">
            {roots.map((root) => (
              <li key={root.id}>
                <Card className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <Folder size={16} className="text-foreground-muted" aria-hidden="true" />
                    {root.displayPath}
                    {root.status === "unavailable" ? (
                      <span className="rounded bg-danger-subtle px-2 py-0.5 text-xs font-medium text-danger">
                        No disponible en este momento
                      </span>
                    ) : null}
                  </span>
                  <span className="flex items-center gap-2">
                    <Button variant="primary" onClick={() => onAnalyze(root.id)}>
                      Analizar
                    </Button>
                    <Tooltip content="Dejar de organizar esta carpeta">
                      <IconButton
                        label="Dejar de organizar esta carpeta"
                        onClick={() => removeMutation.mutate(root.id)}
                        disabled={removeMutation.isPending}
                      >
                        <Trash2 size={14} />
                      </IconButton>
                    </Tooltip>
                  </span>
                </Card>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </section>
  );
}
