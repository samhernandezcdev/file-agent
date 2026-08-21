import { useCallback, useEffect, useRef, useState } from "react";
import { Folder } from "lucide-react";
import type { BatchApplyResultView, ManagedRootUnavailableResultView } from "@file-agent/desktop-types";
import { CompletionNotice } from "./components/ui/CompletionNotice";
import { DestinationSetupCompletionNotice } from "./components/ui/DestinationSetupCompletionNotice";
import { UndoCompletionNotice } from "./components/ui/UndoCompletionNotice";
import { StepIndicator, type StepState } from "./components/ui/StepIndicator";
import { Tooltip } from "./components/ui/Tooltip";
import { Sidebar, type SidebarDestination } from "./components/Sidebar";
import type { RustOutcome } from "./desktop";
import { ApplyResultsScreen } from "./features/apply/ApplyResultsScreen";
import { HistoryDetailScreen } from "./features/history/HistoryDetailScreen";
import { HistoryScreen } from "./features/history/HistoryScreen";
import { ManagedRootsScreen } from "./features/managed-roots/ManagedRootsScreen";
import { useManagedRootsQuery } from "./features/managed-roots/useManagedRoots";
import { PlanScreen } from "./features/organization-plan/PlanScreen";
import { appendCompletion, removeCompletion, type RetainedCompletion } from "./lib/completionInbox";
import {
  completionPresentation,
  destinationSetupCompletionPresentation,
  undoCompletionPresentation,
  type DestinationSetupOutcome,
  type UndoOutcome,
} from "./lib/outcomeMessages";
import "./App.css";

type Screen =
  | { name: "roots" }
  | { name: "plan"; managedRootId: string }
  | { name: "results"; result: BatchApplyResultView }
  | { name: "history" }
  | { name: "historyDetail"; batchId: string };

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
  const [retainedCompletions, setRetainedCompletions] = useState<
    RetainedCompletion<ApplyOutcome>[]
  >([]);
  const [retainedDestinationSetupCompletions, setRetainedDestinationSetupCompletions] = useState<
    RetainedCompletion<DestinationSetupOutcome>[]
  >([]);
  const [retainedUndoCompletions, setRetainedUndoCompletions] = useState<
    RetainedCompletion<UndoOutcome>[]
  >([]);
  const [applying, setApplying] = useState(false);
  const rootsQuery = useManagedRootsQuery();

  // Read by onApplyCompleted/onDestinationSetupCompleted, which are bound
  // once at mutate()-call time inside PlanScreen and can fire long after
  // this component re-rendered (or PlanScreen unmounted) -- a plain
  // closure over `screen` would see whatever screen was active when the
  // callback was created, not when it actually runs. The ref always
  // reflects the current screen.
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
      appendCompletion(
        prev,
        { id: crypto.randomUUID(), correlationId: managedRootId, outcome, receivedAt: Date.now() },
        (entry) => completionPresentation(entry.outcome).kind !== "unknown",
      ),
    );
  }, []);

  // FA-017.4 §2: destination_setup.prepare has no dedicated results
  // screen (FA-017.2 §12 -- deliberately absent from History, and there
  // is nothing else to navigate to). The "still there" branch is
  // therefore a no-op, not a screen transition: PlanScreen's own local
  // `destinationResults` state already renders the per-category result
  // banner in that case, so App.tsx has nothing to do except avoid a
  // duplicate notice.
  const onDestinationSetupCompleted = useCallback(
    (managedRootId: string, outcome: DestinationSetupOutcome) => {
      const current = screenRef.current;
      if (current.name === "plan" && current.managedRootId === managedRootId) {
        return;
      }
      setRetainedDestinationSetupCompletions((prev) =>
        appendCompletion(
          prev,
          { id: crypto.randomUUID(), correlationId: managedRootId, outcome, receivedAt: Date.now() },
          (entry) => destinationSetupCompletionPresentation(entry.outcome).kind !== "unknown",
        ),
      );
    },
    [],
  );

  // FA-017.5 Part 9/26: Undo can only ever originate from
  // historyDetail(batchId) (Major 1's own removal of any compact-card
  // shortcut) -- so the "still there?" check is exactly
  // screen.name==="historyDetail" && screen.batchId===batchId, never a
  // managedRootId comparison. The "still there" branch is a no-op (like
  // destination-setup's own): HistoryDetailScreen's own query invalidation
  // + refetch already updates the row in place.
  const onUndoCompleted = useCallback((batchId: string, outcome: UndoOutcome) => {
    const current = screenRef.current;
    if (current.name === "historyDetail" && current.batchId === batchId) {
      return;
    }
    setRetainedUndoCompletions((prev) =>
      appendCompletion(
        prev,
        { id: crypto.randomUUID(), correlationId: batchId, outcome, receivedAt: Date.now() },
        (entry) => undoCompletionPresentation(entry.outcome).kind !== "unknown",
      ),
    );
  }, []);

  function openCompletion(entry: RetainedCompletion<ApplyOutcome>) {
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

  // FA-017.4 §2.2/Part 6: NOTICE NAVIGATION != REANALYSIS -- this only
  // ever navigates to the exact managedRootId the notice itself carries
  // (never the currently-active root, never inferred). The plan screen's
  // own existing FA-017.2 invalidated-plan gate is what actually requires
  // an explicit "Analizar de nuevo" once the user gets there; nothing
  // here triggers analysis.run/plan.create/destination_setup.prepare.
  function openDestinationSetupCompletion(entry: RetainedCompletion<DestinationSetupOutcome>) {
    setRetainedDestinationSetupCompletions((prev) => removeCompletion(prev, entry.id));
    setScreen({ name: "plan", managedRootId: entry.correlationId });
  }

  function dismissDestinationSetupCompletion(id: string) {
    setRetainedDestinationSetupCompletions((prev) => removeCompletion(prev, id));
  }

  // FA-017.5 Part 27: pure navigation to the exact originating batch's
  // detail screen -- never itself retries/starts an Undo, never infers
  // success/failure. HistoryDetailScreen's own authoritative refetch is
  // what shows the truthful current state once the user arrives.
  function openUndoCompletion(entry: RetainedCompletion<UndoOutcome>) {
    setRetainedUndoCompletions((prev) => removeCompletion(prev, entry.id));
    setScreen({ name: "historyDetail", batchId: entry.correlationId });
  }

  function dismissUndoCompletion(id: string) {
    setRetainedUndoCompletions((prev) => removeCompletion(prev, id));
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

  // FA-017.4 §2.2/Part 5: two structurally separate state arrays (apply
  // vs destination-setup notices are never merged as persistence/semantic
  // models -- different outcome DTOs, different presentation functions,
  // different eligibility for History) merged ONLY here, at render time,
  // purely so they read as one coherent chronological "what just
  // happened" region for the user.
  const mergedNotices: (
    | { kind: "apply"; entry: RetainedCompletion<ApplyOutcome> }
    | { kind: "destinationSetup"; entry: RetainedCompletion<DestinationSetupOutcome> }
    | { kind: "undo"; entry: RetainedCompletion<UndoOutcome> }
  )[] = [
    ...retainedCompletions.map((entry) => ({ kind: "apply" as const, entry })),
    ...retainedDestinationSetupCompletions.map((entry) => ({
      kind: "destinationSetup" as const,
      entry,
    })),
    ...retainedUndoCompletions.map((entry) => ({ kind: "undo" as const, entry })),
  ].sort((a, b) => a.entry.receivedAt - b.entry.receivedAt);

  // FA-017.4 Part 14: direct same-root reanalysis from Results, reusing
  // the already-existing BatchApplyResultView.managedRootId field (no new
  // backend field). Extracted to a plain local const before the closure
  // -- TypeScript does not propagate a discriminated-union narrowing
  // into a nested arrow function's closure over the same captured value
  // (the exact closure-narrowing gap FA-017.2 §7 already hit once);
  // narrowing a plain `string | null` local does propagate correctly.
  // `null` when every selected id failed lineage resolution entirely --
  // ApplyResultsScreen falls back to its own existing "Volver a la
  // carpeta" (→ roots) in that rare case, never a crash.
  const resultsManagedRootId = screen.name === "results" ? screen.result.managedRootId : null;
  const resultsScreenReanalyzeHandler =
    resultsManagedRootId !== null
      ? () => setScreen({ name: "plan", managedRootId: resultsManagedRootId })
      : null;

  return (
    // FA-017.6 Part 11/12: min-h-screen only guaranteed the shell was AT
    // LEAST one viewport tall -- with no ancestor giving it a definite
    // (capped) height, a long Plan file list simply grew the whole
    // shell taller than the viewport, so `main`'s own overflow-y-auto
    // below never actually engaged (nothing bounded it), and the real
    // scroll ancestor was the document itself -- taking Sidebar along
    // with it. h-screen + overflow-hidden caps the shell at exactly one
    // viewport; `main` is now the app's one real, intentional scroll
    // ancestor.
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar
        active={screen.name === "history" || screen.name === "historyDetail" ? "historial" : "carpetas"}
        onNavigate={navigate}
      />

      <main className="flex-1 overflow-y-auto px-8 py-6">
        {mergedNotices.length > 0 ? (
          <div className="mb-4 flex flex-col gap-2" aria-label="Avisos de organización">
            {mergedNotices.map((notice) => {
              if (notice.kind === "apply") {
                return (
                  <CompletionNotice
                    key={notice.entry.id}
                    entry={notice.entry}
                    onOpen={() => openCompletion(notice.entry)}
                    onDismiss={() => dismissCompletion(notice.entry.id)}
                  />
                );
              }
              if (notice.kind === "destinationSetup") {
                return (
                  <DestinationSetupCompletionNotice
                    key={notice.entry.id}
                    entry={notice.entry}
                    onOpen={() => openDestinationSetupCompletion(notice.entry)}
                    onDismiss={() => dismissDestinationSetupCompletion(notice.entry.id)}
                  />
                );
              }
              return (
                <UndoCompletionNotice
                  key={notice.entry.id}
                  entry={notice.entry}
                  onOpen={() => openUndoCompletion(notice.entry)}
                  onDismiss={() => dismissUndoCompletion(notice.entry.id)}
                />
              );
            })}
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
            onDestinationSetupCompleted={onDestinationSetupCompleted}
            onChooseAnotherFolder={() => setScreen({ name: "roots" })}
            onViewHistory={() => setScreen({ name: "history" })}
          />
        ) : null}

        {screen.name === "results" ? (
          <ApplyResultsScreen
            result={screen.result}
            onViewHistory={() => setScreen({ name: "history" })}
            onDone={() => setScreen({ name: "roots" })}
            onReanalyze={resultsScreenReanalyzeHandler}
          />
        ) : null}

        {screen.name === "history" ? (
          <HistoryScreen
            onOpenBatch={(batchId) => setScreen({ name: "historyDetail", batchId })}
            onChooseAnotherFolder={() => setScreen({ name: "roots" })}
          />
        ) : null}

        {screen.name === "historyDetail" ? (
          <HistoryDetailScreen
            batchId={screen.batchId}
            onBack={() => setScreen({ name: "history" })}
            onUndoCompleted={onUndoCompleted}
          />
        ) : null}
      </main>
    </div>
  );
}

export default App;
