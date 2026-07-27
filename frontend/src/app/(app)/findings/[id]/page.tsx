"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import {
  CategoryBadge,
  FindingStatusBadge,
  SeverityBadge,
} from "@/components/badges";
import { ErrorState } from "@/components/data-states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatRelativeTime } from "@/lib/display";
import { useApiResource } from "@/lib/use-api";

function BackLink() {
  return (
    <Button
      render={<Link href="/findings" />}
      nativeButton={false}
      variant="ghost"
      size="sm"
      className="w-fit"
    >
      <ArrowLeft className="size-4" />
      Back to findings
    </Button>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export default function FindingDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const {
    data: finding,
    error,
    loading,
  } = useApiResource(() => api.finding(id), [id]);

  if (error) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-4">
        <BackLink />
        <ErrorState message="This finding could not be loaded." />
      </div>
    );
  }

  if (loading || !finding) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-4">
        <BackLink />
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <BackLink />

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <CategoryBadge category={finding.category} />
          <FindingStatusBadge status={finding.status} />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">{finding.title}</h1>
        <p className="text-sm text-muted-foreground">
          {finding.targetName} · {Math.round(finding.confidence * 100)}% confidence
          · discovered {formatRelativeTime(finding.discoveredAt)}
        </p>
      </div>

      <Section title="Description">
        <p className="text-sm leading-relaxed text-muted-foreground">
          {finding.description}
        </p>
      </Section>

      <Section title="Patient safety impact">
        <p className="text-sm leading-relaxed text-muted-foreground">
          {finding.patientSafetyImpact}
        </p>
      </Section>

      <Section title="Reproduction steps">
        <ol className="flex list-decimal flex-col gap-2 pl-5 text-sm text-muted-foreground">
          {finding.reproductionSteps.map((step, index) => (
            <li key={index}>{step}</li>
          ))}
        </ol>
      </Section>

      <div className="grid gap-4 md:grid-cols-2">
        <Section title="Attack prompt">
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-muted/50 p-3 font-mono text-xs">
            {finding.attackPrompt}
          </pre>
        </Section>
        <Section title="Target response">
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-muted/50 p-3 font-mono text-xs">
            {finding.targetResponse}
          </pre>
        </Section>
      </div>

      <Section title="Recommended remediation">
        <p className="text-sm leading-relaxed text-muted-foreground">
          {finding.recommendation}
        </p>
      </Section>
    </div>
  );
}
