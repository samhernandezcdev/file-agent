import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Never optimistically claim a file mutation succeeded: staleness
      // is handled by explicit invalidation on mutation success, not by
      // aggressive background refetching.
      retry: false,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
});
