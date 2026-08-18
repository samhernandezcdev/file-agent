/**
 * The ONE module allowed to import Tauri frontend APIs (FA-017 design
 * plan §"FRONTEND TAURI BOUNDARY"). Every feature calls these typed
 * wrappers -- no React component anywhere else calls `invoke()` directly
 * or constructs a command-name string itself.
 *
 * UI intent is never authorization: this module forwards a command name
 * and params to Rust's `desktop_call`, and returns whatever discriminated
 * `RustOutcome` Rust resolves -- it never locally fabricates a "success",
 * never caches a `safe`/`ready`/`authorized` claim, and never retries a
 * lost request automatically.
 */
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import type {
  AnalysisFailureView,
  AnalysisResultView,
  AnalyzedItemView,
  ApplyResultView,
  BatchApplyResultView,
  BatchHistoryEntryView,
  HistoryLookupFailureView,
  ManagedRootListView,
  ManagedRootUnavailableResultView,
  ManagedRootView,
  PlanView,
  RecentHistoryView,
  RemoveManagedRootResultView,
  RestoreResultView,
  ReviewActionResultView,
  UndoResultView,
} from "@file-agent/desktop-types";

/** Mirrors Rust's `sidecar::RequestOutcome` wire shape exactly. */
export type RustOutcome<T> =
  | { outcome: "ok"; result: T }
  | { outcome: "product_error"; kind: string; code: string; message: string }
  | { outcome: "unknown_mutation_outcome" }
  | { outcome: "retryable_interrupted" }
  | { outcome: "transport_unavailable"; message: string };

async function call<T>(command: string, params: Record<string, unknown>): Promise<RustOutcome<T>> {
  return invoke<RustOutcome<T>>("desktop_call", { command, params });
}

export const desktop = {
  managedRoots: {
    add: (path: string) => call<ManagedRootView>("managed_roots.add", { path }),
    remove: (managedRootId: string) =>
      call<RemoveManagedRootResultView>("managed_roots.remove", { managedRootId }),
    list: () => call<ManagedRootListView>("managed_roots.list", {}),
  },
  analysis: {
    run: (managedRootId: string) =>
      call<AnalysisResultView | ManagedRootUnavailableResultView>("analysis.run", {
        managedRootId,
      }),
    reanalyzeFile: (fileId: string) =>
      call<AnalyzedItemView | AnalysisFailureView>("analysis.reanalyze_file", { fileId }),
  },
  plan: {
    create: (policyDecisionIds: string[]) =>
      call<PlanView | ManagedRootUnavailableResultView>("plan.create", { policyDecisionIds }),
  },
  review: {
    approve: (policyDecisionId: string, note?: string) =>
      call<ReviewActionResultView>("review.approve", { policyDecisionId, note }),
    skip: (policyDecisionId: string, note?: string) =>
      call<ReviewActionResultView>("review.skip", { policyDecisionId, note }),
  },
  apply: {
    item: (policyDecisionId: string) =>
      call<ApplyResultView>("apply.item", { policyDecisionId }),
    items: (policyDecisionIds: string[]) =>
      call<BatchApplyResultView | ManagedRootUnavailableResultView>("apply.items", {
        policyDecisionIds,
      }),
  },
  history: {
    getBatch: (batchId: string, includeItems = false) =>
      call<BatchHistoryEntryView | HistoryLookupFailureView>("history.get_batch", {
        batchId,
        includeItems,
      }),
    listRecent: (limit = 20) => call<RecentHistoryView>("history.list_recent", { limit }),
  },
  recovery: {
    undoTransaction: (transactionId: string) =>
      call<UndoResultView>("recovery.undo_transaction", { transactionId }),
    restoreCapture: (captureId: string) =>
      call<RestoreResultView>("recovery.restore_capture", { captureId }),
  },
  /** The one raw-path source in the whole system: the native folder
   * picker. Returns null on cancel -- callers must never register
   * anything when this resolves to null. */
  pickFolder: async (): Promise<string | null> => {
    // E2E-only escape hatch. @wdio/tauri-plugin's browser.tauri.mock()
    // only intercepts calls routed through window.__TAURI__.core.invoke
    // -- it cannot see this call, because @tauri-apps/plugin-dialog's
    // open() (like every idiomatic Tauri app, including this one) calls
    // the ES-imported `invoke` from @tauri-apps/api/core directly, a
    // wholly separate reference that never touches window.__TAURI__.
    // Without this override, an automated E2E click on "Agregar carpeta"
    // opens the REAL native dialog every time -- traced live: it
    // returned a real, unrelated Downloads subfolder (read-only
    // analyzed, never mutated, but a genuine isolation violation this
    // closes). Gated by VITE_E2E; never present in a normal build.
    if (import.meta.env.VITE_E2E === "true") {
      const override = (window as { __E2E_PICK_FOLDER_OVERRIDE__?: string })
        .__E2E_PICK_FOLDER_OVERRIDE__;
      if (override !== undefined) {
        return override;
      }
    }
    const selected = await open({ directory: true, multiple: false });
    return typeof selected === "string" ? selected : null;
  },
};

export type Desktop = typeof desktop;
