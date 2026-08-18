import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { desktop } from "../../desktop";

export function analysisQueryKey(managedRootId: string) {
  return ["analysis", managedRootId] as const;
}

export function useAnalysisQuery(managedRootId: string) {
  return useQuery({
    queryKey: analysisQueryKey(managedRootId),
    queryFn: () => desktop.analysis.run(managedRootId),
  });
}

export function planQueryKey(policyDecisionIds: readonly string[]) {
  return ["plan", ...policyDecisionIds] as const;
}

/** plan.create is SAFE_RETRY and read-only (preview is not authorization)
 * -- refetching after a review decision is exactly how the UI learns the
 * item's new status; it is never locally converted from REVIEW to READY. */
export function usePlanQuery(policyDecisionIds: readonly string[]) {
  return useQuery({
    queryKey: planQueryKey(policyDecisionIds),
    queryFn: () => desktop.plan.create([...policyDecisionIds]),
    enabled: policyDecisionIds.length > 0,
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

export function useApplyItemsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (policyDecisionIds: string[]) => desktop.apply.items(policyDecisionIds),
    onSuccess: () => {
      // Managed roots' status/history can change after an apply -- refetch
      // rather than assume anything locally.
      queryClient.invalidateQueries({ queryKey: ["managed-roots"] });
      queryClient.invalidateQueries({ queryKey: ["history"] });
    },
  });
}
