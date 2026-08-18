import { useState } from "react";
import type { BatchApplyResultView } from "@file-agent/desktop-types";
import { ApplyResultsScreen } from "./features/apply/ApplyResultsScreen";
import { HistoryScreen } from "./features/history/HistoryScreen";
import { ManagedRootsScreen } from "./features/managed-roots/ManagedRootsScreen";
import { PlanScreen } from "./features/organization-plan/PlanScreen";
import "./App.css";

type Screen =
  | { name: "roots" }
  | { name: "plan"; managedRootId: string }
  | { name: "results"; result: BatchApplyResultView }
  | { name: "history" };

function App() {
  const [screen, setScreen] = useState<Screen>({ name: "roots" });

  return (
    <main className="fa-app">
      <nav aria-label="Navegación principal">
        <button type="button" onClick={() => setScreen({ name: "roots" })}>
          Carpetas
        </button>
        <button type="button" onClick={() => setScreen({ name: "history" })}>
          Historial
        </button>
      </nav>

      {screen.name === "roots" ? (
        <ManagedRootsScreen
          onAnalyze={(managedRootId) => setScreen({ name: "plan", managedRootId })}
        />
      ) : null}

      {screen.name === "plan" ? (
        <PlanScreen
          managedRootId={screen.managedRootId}
          onApplied={(result) => setScreen({ name: "results", result })}
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
  );
}

export default App;
