import type { ReactNode } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { analysisQueryKey, useAnalysisQuery } from "./usePlanFlow";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));

const EMPTY_ANALYSIS_RESULT = {
  outcome: "ok",
  result: {
    outcome: "ok",
    scanId: "scan-1",
    filesDiscovered: 0,
    protectedTreesMessage: null,
    failures: [],
    items: [],
  },
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function makeWrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function analysisRunCalls() {
  return vi
    .mocked(invoke)
    .mock.calls.filter(([, args]) => (args as { command?: string })?.command === "analysis.run");
}

/** FA-017.2 Round-2 remediation, Major 1: useAnalysisQuery/usePlanQuery use
 * a FUNCTION refetchOnMount -- `(query) => !query.state.isInvalidated` --
 * instead of a global staleTime:Infinity + refetchOnMount:false. These two
 * tests prove that function is behaviorally neutral for every case except
 * the one destination-setup itself introduces: an ordinary, never-
 * invalidated query keeps exactly its pre-existing default remount-refetch
 * behavior (test 1); only a query invalidateQueries has explicitly marked
 * isInvalidated (refetchType: "none", exactly what
 * useDestinationSetupMutation does) skips that remount-refetch (test 2). */
describe("useAnalysisQuery -- refetchOnMount(query) neutrality", () => {
  it("an ordinary (never-invalidated) query still auto-refetches on remount -- unchanged default TanStack behavior", async () => {
    vi.mocked(invoke).mockReset();
    vi.mocked(invoke).mockResolvedValue(EMPTY_ANALYSIS_RESULT);
    const client = makeClient();
    const wrapper = makeWrapper(client);

    const first = renderHook(() => useAnalysisQuery("root-1"), { wrapper });
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
    first.unmount();

    const second = renderHook(() => useAnalysisQuery("root-1"), { wrapper });
    await waitFor(() => expect(analysisRunCalls()).toHaveLength(2));
    await waitFor(() => expect(second.result.current.isSuccess).toBe(true));
  });

  it("a query invalidated with refetchType: 'none' does NOT auto-refetch on remount -- the scoped destination-setup behavior", async () => {
    vi.mocked(invoke).mockReset();
    vi.mocked(invoke).mockResolvedValue(EMPTY_ANALYSIS_RESULT);
    const client = makeClient();
    const wrapper = makeWrapper(client);

    const first = renderHook(() => useAnalysisQuery("root-1"), { wrapper });
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
    first.unmount();

    // Exactly what useDestinationSetupMutation's onSuccess does.
    await client.invalidateQueries({
      queryKey: analysisQueryKey("root-1"),
      refetchType: "none",
    });
    expect(client.getQueryState(analysisQueryKey("root-1"))?.isInvalidated).toBe(true);

    renderHook(() => useAnalysisQuery("root-1"), { wrapper });
    // Give any potential background refetch a real chance to fire before
    // asserting its absence.
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(analysisRunCalls()).toHaveLength(1);
  });
});
