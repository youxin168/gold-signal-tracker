import { useQuery } from "@tanstack/react-query";
import { getSnapshot } from "@/lib/public-snapshot";

export const SNAPSHOT_KEY = ["public-snapshot"] as const;

/** Refresh the shared published file, never the market feed or signal engine. */
export function useSnapshot() {
  return useQuery({
    queryKey: SNAPSHOT_KEY,
    queryFn: ({ signal }) => getSnapshot(signal),
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchInterval: 60_000,
    retry: 1,
  });
}
