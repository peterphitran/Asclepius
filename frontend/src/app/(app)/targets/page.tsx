"use client";

import { TargetHealthBadge } from "@/components/badges";
import { ErrorState, TableSkeleton } from "@/components/data-states";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatRelativeTime } from "@/lib/display";
import { useApiResource } from "@/lib/use-api";

export default function TargetsPage() {
  const { data: targets, error, loading } = useApiResource(() => api.targets());

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Targets</h1>
        <p className="text-sm text-muted-foreground">
          The clinical AI systems Asclepius attacks, scoped to your organization.
        </p>
      </div>

      {error ? (
        <ErrorState message={error} />
      ) : loading || !targets ? (
        <TableSkeleton />
      ) : (
        <div className="rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Environment</TableHead>
                <TableHead>Health</TableHead>
                <TableHead className="text-right">Open</TableHead>
                <TableHead className="text-right">Critical</TableHead>
                <TableHead>Last scanned</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {targets.map((target) => (
                <TableRow key={target.id}>
                  <TableCell className="font-medium">{target.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {target.model}
                  </TableCell>
                  <TableCell className="text-muted-foreground capitalize">
                    {target.environment}
                  </TableCell>
                  <TableCell>
                    <TargetHealthBadge health={target.health} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {target.openFindings}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {target.criticalFindings > 0 ? (
                      <span className="text-red-400">{target.criticalFindings}</span>
                    ) : (
                      <span className="text-muted-foreground">0</span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {target.lastScannedAt
                      ? formatRelativeTime(target.lastScannedAt)
                      : "Never"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
