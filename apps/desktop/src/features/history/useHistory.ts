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

export function useUndoTransactionMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (transactionId: string) => desktop.recovery.undoTransaction(transactionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["history"] });
      queryClient.invalidateQueries({ queryKey: ["managed-roots"] });
    },
  });
}
