import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import {
  CategoryBadge,
  FindingStatusBadge,
  SeverityBadge,
} from "@/components/badges";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatRelativeTime } from "@/lib/display";
import type { Finding } from "@/lib/types";

export function FindingsTable({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
        No findings to show.
      </div>
    );
  }

  return (
    <div className="rounded-xl border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Finding</TableHead>
            <TableHead>Severity</TableHead>
            <TableHead>Category</TableHead>
            <TableHead>Target</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Confidence</TableHead>
            <TableHead>Discovered</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {findings.map((finding) => (
            <TableRow key={finding.id}>
              <TableCell className="font-medium">
                <Link
                  href={`/findings/${finding.id}`}
                  className="flex max-w-[26rem] items-center gap-1 hover:underline"
                >
                  <span className="min-w-0 truncate">{finding.title}</span>
                  <ArrowUpRight className="size-3.5 shrink-0 text-muted-foreground" />
                </Link>
              </TableCell>
              <TableCell>
                <SeverityBadge severity={finding.severity} />
              </TableCell>
              <TableCell>
                <CategoryBadge category={finding.category} short />
              </TableCell>
              <TableCell className="text-muted-foreground">
                {finding.targetName}
              </TableCell>
              <TableCell>
                <FindingStatusBadge status={finding.status} />
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {Math.round(finding.confidence * 100)}%
              </TableCell>
              <TableCell className="text-muted-foreground">
                {formatRelativeTime(finding.discoveredAt)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
