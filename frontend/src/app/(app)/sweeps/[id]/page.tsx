"use client";

import { useParams } from "next/navigation";

import { CampaignStatusBadge, CategoryBadge } from "@/components/badges";
import { ErrorState } from "@/components/data-states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { AGENT_META, STEP_STATUS_META, formatRelativeTime } from "@/lib/display";
import type { AgentName } from "@/lib/types";
import { useApiResource } from "@/lib/use-api";
import { cn } from "@/lib/utils";

function AgentIcon({ agent, className }: { agent: AgentName; className?: string }) {
  const meta = AGENT_META[agent];
  const Icon = meta.icon;
  return <Icon className={cn("size-4 shrink-0", meta.accent, className)} />;
}

export default function SweepDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const {
    data: sweep,
    error,
    loading,
  } = useApiResource(() => api.sweep(id), [id]);

  if (error) {
    return (
      <div className="mx-auto max-w-4xl">
        <ErrorState message="This sweep could not be loaded." />
      </div>
    );
  }

  if (loading || !sweep) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-4">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {sweep.campaignName}
          </h1>
          <CampaignStatusBadge status={sweep.status} />
        </div>
        <p className="text-sm text-muted-foreground">Target: {sweep.targetName}</p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-4 pt-6">
          <div>
            <div className="mb-1.5 flex items-center justify-between text-sm">
              <span className="font-medium">Progress</span>
              <span className="tabular-nums text-muted-foreground">
                {sweep.completedCases}/{sweep.totalCases} cases · {sweep.progress}%
              </span>
            </div>
            <Progress value={sweep.progress} />
          </div>

          {sweep.currentActivity ? (
            <div className="flex items-center gap-2 rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
              {sweep.currentAgent ? <AgentIcon agent={sweep.currentAgent} /> : null}
              <span>{sweep.currentActivity}</span>
            </div>
          ) : null}

          <div className="flex gap-6 text-sm">
            <div>
              <div className="text-2xl font-semibold tabular-nums text-red-400">
                {sweep.findingsCount}
              </div>
              <div className="text-muted-foreground">Vulnerabilities</div>
            </div>
            <div>
              <div className="text-2xl font-semibold tabular-nums">
                {sweep.progress}%
              </div>
              <div className="text-muted-foreground">Complete</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Activity feed</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {sweep.steps.map((step) => {
            const stepMeta = STEP_STATUS_META[step.status];
            return (
              <div
                key={step.id}
                className="flex items-start gap-3 rounded-lg border p-3"
              >
                <AgentIcon agent={step.agent} className="mt-0.5" />
                <div className="flex flex-1 flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium">
                      {AGENT_META[step.agent].label}
                    </span>
                    <CategoryBadge category={step.category} short />
                    <span className="text-muted-foreground">{step.strategy}</span>
                  </div>
                  <p className="text-sm text-muted-foreground">{step.detail}</p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <Badge
                    variant="outline"
                    className={cn("font-medium", stepMeta.badge)}
                  >
                    <span
                      className={cn("mr-1.5 size-1.5 rounded-full", stepMeta.dot)}
                    />
                    {stepMeta.label}
                  </Badge>
                  {step.confidence !== null ? (
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {Math.round(step.confidence * 100)}%
                    </span>
                  ) : null}
                  <span className="text-xs text-muted-foreground">
                    {formatRelativeTime(step.timestamp)}
                  </span>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
