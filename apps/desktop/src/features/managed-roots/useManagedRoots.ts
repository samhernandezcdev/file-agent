import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { desktop } from "../../desktop";

export const managedRootsQueryKey = ["managed-roots"] as const;

/** TanStack Query owns this backend state -- mutations invalidate/refetch
 * rather than optimistically fabricating a new list locally. */
export function useManagedRootsQuery() {
  return useQuery({
    queryKey: managedRootsQueryKey,
    queryFn: () => desktop.managedRoots.list(),
  });
}

export function useAddManagedRootMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (path: string) => desktop.managedRoots.add(path),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: managedRootsQueryKey }),
  });
}

export function useRemoveManagedRootMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (managedRootId: string) => desktop.managedRoots.remove(managedRootId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: managedRootsQueryKey }),
  });
}
