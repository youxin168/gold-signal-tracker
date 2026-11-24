import type { ReactNode } from "react";
import { useSnapshot } from "@/hooks/use-snapshot";
import type { Snapshot } from "@/lib/public-snapshot";
import { ErrorState, LoadingBlock } from "@/components/bits";

export function SnapshotGate({ children }: { children: (s: Snapshot) => ReactNode }) {
  const { data, error, isLoading, refetch } = useSnapshot();
  if (isLoading) return <LoadingBlock />;
  if (!data) return <ErrorState error={error} onRetry={() => refetch()} />;
  return <>{children(data)}</>;
}
