import { useState } from "react";
import { Folder, FolderPlus } from "lucide-react";
import { Banner } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { desktop } from "../../desktop";
import { guidanceForOutcome } from "../../lib/outcomeMessages";
import {
  useAddManagedRootMutation,
  useManagedRootsQuery,
  useRemoveManagedRootMutation,
} from "./useManagedRoots";

/** One empty state, keyed only on managedRoots.length === 0 (FA-017.1
 * §22) -- no localStorage, no first-run/returning distinction anywhere in
 * the frontend. Serves a genuinely first-time user and a returning user
 * with no roots left equally well. */
function FirstRunEmptyState({ onAddFolder, busy }: { onAddFolder: () => void; busy: boolean }) {
  return (
    <EmptyState
      icon={FolderPlus}
      title="Organiza una carpeta con FileAgent"
      detail={
        <>
          <ol className="list-inside list-decimal space-y-1 text-left">
            <li>Elige una carpeta</li>
            <li>FileAgent analiza los archivos</li>
            <li>Revisa los cambios</li>
            <li>Organiza cuando estés listo</li>
          </ol>
          <p className="mt-3">FileAgent nunca elimina archivos automáticamente.</p>
        </>
      }
      action={
        <Button variant="primary" onClick={onAddFolder} disabled={busy}>
          Elegir una carpeta
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
                    <Button
                      variant="danger"
                      onClick={() => removeMutation.mutate(root.id)}
                      disabled={removeMutation.isPending}
                    >
                      Dejar de organizar esta carpeta
                    </Button>
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
