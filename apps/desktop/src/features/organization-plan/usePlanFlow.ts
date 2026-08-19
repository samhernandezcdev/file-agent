import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { DestinationCategory } from "@file-agent/desktop-types";
import { desktop } from "../../desktop";

export function analysisQueryKey(managedRootId: string) {
  return ["analysis", managedRootId] as const;
}

/** refetchOnMount as a FUNCTION (FA-017.2 Round-2 remediation, Major 1 --
 * verified against the installed @tanstack/query-core@5.101.4's
 * queryObserver.js): `(query) => !query.state.isInvalidated` returns
 * `true` -- the library's own hard default when the option is entirely
 * unset -- for every query that was never explicitly invalidated, which
 * is every analysis query in every pre-existing/unrelated codepath (only
 * useDestinationSetupMutation below ever calls invalidateQueries against
 * this key, and only ever with refetchType:"none"). This makes the
 * function provably behaviorally neutral for ordinary analysis lifecycle
 * -- see usePlanFlow.neutrality.test.ts. It returns `false` ONLY in the
 * one state this feature itself introduces: invalidated-but-not-yet-
 * refetched, which prevents shouldFetchOnMount's default remount-refetch
 * in exactly that state (confirmed in queryObserver.js: shouldFetchOn's
 * `value !== false && isStale(...)` short-circuits to false once the
 * function returns false, regardless of elapsed-time staleness). Neither
 * staleTime nor any other option here is touched -- ordinary elapsed-time
 * refetch-on-mount behavior for a query that was never invalidated is
 * completely unchanged from before this feature existed. Only an
 * explicit .refetch() (wired to "Analizar de nuevo") ever fetches fresh
 * data while a query sits invalidated-and-idle. */
export function useAnalysisQuery(managedRootId: string) {
  return useQuery({
    queryKey: analysisQueryKey(managedRootId),
    queryFn: () => desktop.analysis.run(managedRootId),
    refetchOnMount: (query) => !query.state.isInvalidated,
  });
}

export function planQueryKey(policyDecisionIds: readonly string[]) {
  return ["plan", ...policyDecisionIds] as const;
}

/** plan.create is SAFE_RETRY and read-only (preview is not authorization)
 * -- refetching after a review decision is exactly how the UI learns the
 * item's new status; it is never locally converted from REVIEW to READY.
 *
 * Same scoped refetchOnMount reasoning as useAnalysisQuery above. Each
 * fresh analysis.run mints brand-new policy_decision_ids (PolicyEngine
 * creates a new PolicyDecision every call -- verified in
 * application/service.py::_analyze_discovered), so a genuine reanalysis
 * naturally produces a NEW queryKey and fetches immediately regardless of
 * this option; it matters specifically for the case where the user
 * navigates away and back WITHOUT reanalyzing -- the same (now possibly
 * invalidated) key must not silently auto-refetch. approve/skip's own
 * invalidateQueries call (default refetchType "active") is unaffected:
 * invalidateQueries always fetches matching active queries directly,
 * regardless of refetchOnMount, which only governs mount-triggered
 * fetching. */
export function usePlanQuery(policyDecisionIds: readonly string[]) {
  return useQuery({
    queryKey: planQueryKey(policyDecisionIds),
    queryFn: () => desktop.plan.create([...policyDecisionIds]),
    enabled: policyDecisionIds.length > 0,
    refetchOnMount: (query) => !query.state.isInvalidated,
  });
}

export function useReviewMutations(policyDecisionIds: readonly string[]) {
  const queryClient = useQueryClient();
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: planQueryKey(policyDecisionIds) });

  const approve = useMutation({
    mutationFn: (policyDecisionId: string) => desktop.review.approve(policyDecisionId),
    onSuccess: invalidate,
  });
  const skip = useMutation({
    mutationFn: (policyDecisionId: string) => desktop.review.skip(policyDecisionId),
    onSuccess: invalidate,
  });
  return { approve, skip };
}

/** `onCompleted` is invoked from this hook's OWN onSuccess (stored
 * directly on the underlying Mutation's options, and updated on every
 * render via TanStack Query's setOptions) -- not from a per-call
 * `mutate(variables, { onSuccess })` callback, which is stored on the
 * MutationObserver instead and is empirically NOT invoked once the
 * observer's owning component (PlanScreen) has unmounted. This is the one
 * mechanism that reliably survives navigating away before an apply
 * resolves (FA-017.1 §19a). */
export function useApplyItemsMutation(
  onCompleted: (outcome: Awaited<ReturnType<typeof desktop.apply.items>>) => void,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (policyDecisionIds: string[]) => desktop.apply.items(policyDecisionIds),
    onSuccess: (outcome) => {
      // Managed roots' status/history can change after an apply -- refetch
      // rather than assume anything locally.
      queryClient.invalidateQueries({ queryKey: ["managed-roots"] });
      queryClient.invalidateQueries({ queryKey: ["history"] });
      onCompleted(outcome);
    },
  });
}

/** FA-017.2. `onCompleted` is invoked from this hook's OWN onSuccess --
 * same hook-level-not-per-call discipline as useApplyItemsMutation above,
 * for the identical reason (survives PlanScreen unmounting before the
 * request resolves).
 *
 * FA-017.2 Round-2 remediation (Major 1): deliberately does NOT cause an
 * automatic refetch of `["analysis", managedRootId]` or
 * `["plan", ...policyDecisionIds]` -- an ordinary invalidateQueries()
 * call (default refetchType "active") would immediately re-fetch these
 * ACTIVE queries the instant a prepare call finished, which is exactly
 * the hidden/automatic re-analysis the design forbids. `refetchType:
 * "none"` marks the old analysis/plan state non-authoritative
 * (Query.state.isInvalidated = true, verified against the installed
 * query-core's invalidateQueries implementation: refetchType "none"
 * returns immediately, never calling refetchQueries) WITHOUT fetching
 * anything. This mark lives in the QueryClient cache, not component
 * state, so it survives PlanScreen unmounting and remounting --
 * combined with useAnalysisQuery/usePlanQuery's scoped refetchOnMount
 * function above (which reads this exact isInvalidated flag to skip the
 * default remount-refetch ONLY while it's true), navigating away and
 * back can no longer silently show the pre-setup plan as if nothing
 * happened, or silently re-run analysis in the background either.
 * PlanScreen reads `queryClient.getQueryState(key)?.isInvalidated`
 * directly (not the observer's own `isStale`, which also reflects
 * ordinary elapsed-time staleness and would misfire constantly under
 * this hook's now-unchanged default staleTime) to gate selection/
 * organize off while invalidated -- "Analizar de nuevo"
 * (analysisQuery.refetch()) remains the only thing that ever clears it
 * (a successful fetch always resets isInvalidated to false, verified in
 * query-core's successState()). Runs regardless of the resolved
 * outcome's shape (ok / partial / unknown_mutation_outcome /
 * product_error / managed_root_unavailable) -- once a prepare round trip
 * has completed at all, the previously-cached plan can no longer be
 * blindly trusted either way. */
export function useDestinationSetupMutation(
  managedRootId: string,
  policyDecisionIds: readonly string[],
  onCompleted: (
    outcome: Awaited<ReturnType<typeof desktop.destinationSetup.prepare>>,
  ) => void,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (destinationCategories: DestinationCategory[]) =>
      desktop.destinationSetup.prepare(managedRootId, destinationCategories),
    onSuccess: (outcome) => {
      queryClient.invalidateQueries({
        queryKey: analysisQueryKey(managedRootId),
        refetchType: "none",
      });
      queryClient.invalidateQueries({
        queryKey: planQueryKey(policyDecisionIds),
        refetchType: "none",
      });
      onCompleted(outcome);
    },
  });
}
