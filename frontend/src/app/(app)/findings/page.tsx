"use client";

import { ErrorState, TableSkeleton } from "@/components/data-states";
import { FindingsTable } from "@/components/findings-table";
import { api } from "@/lib/api";
import { useApiResource } from "@/lib/use-api";

export default function FindingsPage() {
  const { data, error, loading } = useApiResource(() => api.findings());

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Findings</h1>
        <p className="text-sm text-muted-foreground">
          Every confirmed vulnerability across your targets.
        </p>
      </div>

      {error ? (
        <ErrorState message={error} />
      ) : loading || !data ? (
        <TableSkeleton />
      ) : (
        <FindingsTable findings={data} />
      )}
    </div>
  );
}
