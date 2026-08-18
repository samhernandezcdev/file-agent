import { useState } from "react";
import { Banner } from "../../components/ui/Banner";
import { Button } from "../../components/ui/Button";
import { desktop } from "../../desktop";
import { guidanceForOutcome } from "../../lib/outcomeMessages";
import {
  useAddManagedRootMutation,
  useManagedRootsQuery,
  useRemoveManagedRootMutation,
} from "./useManagedRoots";

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

  return (
    <section aria-labelledby="managed-roots-heading">
      <h1 id="managed-roots-heading">Carpetas que FileAgent puede organizar</h1>
      <p>
        FileAgent organiza tus archivos de forma segura. Revisa todo antes. Deshaz cualquier
        cambio.
      </p>

      <Button
        variant="primary"
        onClick={handleAddFolder}
        disabled={pickerBusy || addMutation.isPending}
      >
        Agregar carpeta
      </Button>

      {addGuidance ? <Banner severity="error" title={addGuidance.title} detail={addGuidance.detail} /> : null}
      {removeGuidance ? (
        <Banner severity="error" title={removeGuidance.title} detail={removeGuidance.detail} />
      ) : null}

      {rootsQuery.isLoading ? <p role="status">Cargando carpetas…</p> : null}
      {rootsQuery.isError ? (
        <Banner severity="error" title="No pudimos cargar tus carpetas en este momento." />
      ) : null}

      {rootsQuery.data?.outcome === "ok" ? (
        rootsQuery.data.result.roots.length === 0 ? (
          <p>Todavía no agregaste ninguna carpeta.</p>
        ) : (
          <ul aria-label="Carpetas administradas">
            {rootsQuery.data.result.roots.map((root) => (
              <li key={root.id}>
                <span>{root.displayPath}</span>
                {root.status === "unavailable" ? (
                  <span className="fa-tag fa-tag-error"> No disponible en este momento</span>
                ) : null}
                <Button onClick={() => onAnalyze(root.id)}>Analizar</Button>
                <Button
                  variant="danger"
                  onClick={() => removeMutation.mutate(root.id)}
                  disabled={removeMutation.isPending}
                >
                  Dejar de organizar esta carpeta
                </Button>
              </li>
            ))}
          </ul>
        )
      ) : null}
    </section>
  );
}
