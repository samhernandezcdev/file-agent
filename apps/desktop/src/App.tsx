import { useCallback, useEffect, useRef, useState } from "react";
import { Folder } from "lucide-react";
import type {
  BatchApplyResultView,
  ManagedRootUnavailableResultView,
} from "@file-agent/desktop-types";
import { CompletionNotice } from "./components/ui/CompletionNotice";
import { StepIndicator, type StepState } from "./components/ui/StepIndicator";
import { Tooltip } from "./components/ui/Tooltip";
import { Sidebar, type SidebarDestination } from "./components/Sidebar";
import type { RustOutcome } from "./desktop";
import { ApplyResultsScreen } from "./features/apply/ApplyResultsScreen";
import { HistoryScreen } from "./features/history/HistoryScreen";
import { ManagedRootsScreen } from "./features/managed-roots/ManagedRootsScreen";
import { useManagedRootsQuery } from "./features/managed-roots/useManagedRoots";
import { PlanScreen } from "./features/organization-plan/PlanScreen";
import { appendCompletion, removeCompletion, type RetainedCompletion } from "./lib/completionInbox";
import { completionPresentation } from "./lib/outcomeMessages";
import "./App.css";

type Screen =
  | { name: "roots" }
  | { name: "plan"; managedRootId: string }
  | { name: "results"; result: BatchApplyResultView }
  | { name: "history" };

type ApplyOutcome = RustOutcome<BatchApplyResultView | ManagedRootUnavailableResultView>;

function stepStatesFor(
  screenName: Screen["name"],
  applying: boolean,
): Record<"carpeta" | "revisar" | "resultado", StepState> {
  if (screenName === "plan") {
    return { carpeta: "done", revisar: applying ? "pending" : "current", resultado: "upcoming" };
  }
  if (screenName === "results") {
    return { carpeta: "done", revisar: "done", resultado: "current" };
  }
  return { carpeta: "current", revisar: "upcoming", resultado: "upcoming" };
}

function App() {
  const [screen, setScreen] = useState<Screen>({ name: "roots" });
  const [retainedCompletions, setRetainedCompletions] = useState<RetainedCompletion[]>([]);
  const [applying, setApplying] = useState(false);
  const rootsQuery = useManagedRootsQuery();

  // Read by onApplyCompleted, which is bound once at mutate()-call time
  // inside PlanScreen and can fire long after this component re-rendered
  // (or PlanScreen unmounted) -- a plain closure over `screen` would see
  // whatever screen was active when the callback was created, not when it
  // actually runs. The ref always reflects the current screen.
  const screenRef = useRef(screen);
  useEffect(() => {
    screenRef.current = screen;
  }, [screen]);

  // Ownership lives here, centrally, not in PlanScreen (FA-017.1 §19a):
  // the mutation's onSuccess survives PlanScreen's unmount (a TanStack
  // Query guarantee), so the same decision procedure applies whether the
  // user is still looking at this root's Revisar screen or navigated away
  // long before the apply resolved.
  const onApplyCompleted = useCallback((managedRootId: string, outcome: ApplyOutcome) => {
    const current = screenRef.current;
    if (current.name === "plan" && current.managedRootId === managedRootId) {
      // Still there: PlanScreen's own mutation state already renders
      // non-ok guidance inline (unchanged FA-017 behavior) -- only a real
      // result transitions the screen.
      const presentation = completionPresentation(outcome);
      if (presentation.kind === "result") {
        setScreen({ name: "results", result: presentation.result });
      }
      return;
    }
    setRetainedCompletions((prev) =>
      appendCompletion(prev, {
        id: crypto.randomUUID(),
        managedRootId,
        outcome,
        receivedAt: Date.now(),
      }),
    );
  }, []);

  function openCompletion(entry: RetainedCompletion) {
    const presentation = completionPresentation(entry.outcome);
    setRetainedCompletions((prev) => removeCompletion(prev, entry.id));
    if (presentation.kind === "result") {
      setScreen({ name: "results", result: presentation.result });
    } else if (presentation.kind === "unknown") {
      setScreen({ name: "history" });
    }
    // known_no_result: no dedicated navigation -- dismiss was the only
    // control offered for it, so opening never reaches this branch.
  }

  function dismissCompletion(id: string) {
    setRetainedCompletions((prev) => removeCompletion(prev, id));
  }

  function navigate(destination: SidebarDestination) {
    setScreen(destination === "carpetas" ? { name: "roots" } : { name: "history" });
  }

  const activeManagedRootId = screen.name === "plan" ? screen.managedRootId : null;
  const activeRoot =
    activeManagedRootId !== null && rootsQuery.data?.outcome === "ok"
      ? rootsQuery.data.result.roots.find((root) => root.id === activeManagedRootId)
      : null;
  const showContextStrip = (screen.name === "plan" || screen.name === "results") && activeRoot;

  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar active={screen.name === "history" ? "historial" : "carpetas"} onNavigate={navigate} />

      <main className="flex-1 overflow-y-auto px-8 py-6">
        {retainedCompletions.length > 0 ? (
          <div className="mb-4 flex flex-col gap-2" aria-label="Avisos de organización">
            {retainedCompletions.map((entry) => (
              <CompletionNotice
                key={entry.id}
                entry={entry}
                onOpen={() => openCompletion(entry)}
                onDismiss={() => dismissCompletion(entry.id)}
              />
            ))}
          </div>
        ) : null}

        {showContextStrip ? (
          <div className="mb-4 flex min-w-0 items-center justify-between gap-4">
            <span className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
              <Folder size={16} className="shrink-0 text-foreground-muted" aria-hidden="true" />
              <Tooltip content={activeRoot.displayPath}>
                <span className="min-w-0 truncate">{activeRoot.displayPath}</span>
              </Tooltip>
              <button
                type="button"
                onClick={() => setScreen({ name: "roots" })}
                className="ml-2 shrink-0 text-sm font-medium text-primary hover:text-primary-hover"
              >
                Cambiar carpeta
              </button>
            </span>
            <span className="shrink-0">
              <StepIndicator states={stepStatesFor(screen.name, applying)} />
            </span>
          </div>
        ) : null}

        {screen.name === "roots" ? (
          <ManagedRootsScreen onAnalyze={(managedRootId) => setScreen({ name: "plan", managedRootId })} />
        ) : null}

        {screen.name === "plan" ? (
          <PlanScreen
            managedRootId={screen.managedRootId}
            onApplyCompleted={onApplyCompleted}
            onApplyPendingChange={setApplying}
          />
        ) : null}

        {screen.name === "results" ? (
          <ApplyResultsScreen
            result={screen.result}
            onViewHistory={() => setScreen({ name: "history" })}
            onDone={() => setScreen({ name: "roots" })}
          />
        ) : null}

        {screen.name === "history" ? <HistoryScreen /> : null}
      </main>
    </div>
  );
}

export default App;
