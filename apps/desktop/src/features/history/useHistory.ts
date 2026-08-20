import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { desktop } from "../../desktop";

export function useRecentHistoryQuery() {
  return useQuery({
    queryKey: ["history", "recent"],
    queryFn: () => desktop.history.listRecent(20),
  });
}

export function useBatchDetailQuery(batchId: string | null) {
  return useQuery({
    queryKey: ["history", "batch", batchId],
    queryFn: () => desktop.history.getBatch(batchId as string, true),
    enabled: batchId !== null,
  });
}

/** FA-017.5 Part 25/26. `onCompleted` is invoked from this hook's OWN
 * onSuccess (stored on the underlying Mutation's options, survives
 * HistoryDetailScreen unmounting -- the same hook-level-not-per-call
 * discipline FA-017.1/FA-017.4 already established for apply/destination-
 * setup) -- never a per-call `mutate(id, {onSuccess})`, which would not
 * survive unmount. `variables` (TanStack Query's own onSuccess second
 * argument) is the transactionId passed to mutate(), needed for the
 * exact batchId+transactionId correlation Part 26 requires -- the caller
 * already knows batchId at the call site. */
export function useUndoTransactionMutation(
  onCompleted: (
    transactionId: string,
    outcome: Awaited<ReturnType<typeof desktop.recovery.undoTransaction>>,
  ) => void,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (transactionId: string) => desktop.recovery.undoTransaction(transactionId),
    onSuccess: (outcome, transactionId) => {
      queryClient.invalidateQueries({ queryKey: ["history"] });
      queryClient.invalidateQueries({ queryKey: ["managed-roots"] });
      onCompleted(transactionId, outcome);
    },
  });
}
