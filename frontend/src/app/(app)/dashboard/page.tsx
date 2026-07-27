"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  ClipboardCheck,
  Radar,
  ShieldAlert,
  Target as TargetIcon,
  type LucideIcon,
} from "lucide-react";

import {
  CampaignStatusBadge,
  CategoryBadge,
  SeverityBadge,
} from "@/components/badges";
import { CategoryChart, SeverityChart } from "@/components/dashboard-charts";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, clearToken, getToken, type DashboardStats } from "@/lib/api";
import { AGENT_META, formatRelativeTime } from "@/lib/display";
import type { Finding, Sweep, Target } from "@/lib/types";
import { cn } from "@/lib/utils";

function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  accent,
}: {
  label: string;
  value: number;
  hint: string;
  icon: LucideIcon;
  accent?: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-3xl tabular-nums">{value}</CardTitle>
        <CardAction>
          <span
            className={cn(
              "flex size-9 items-center justify-center rounded-lg",
              accent
                ? "bg-amber-500/15 text-amber-400"
                : "bg-muted text-muted-foreground",
            )}
          >
            <Icon className="size-4.5" />
          </span>
        </CardAction>
      </CardHeader>
      <CardFooter className="text-sm text-muted-foreground">{hint}</CardFooter>
    </Card>
  );
}

function DashboardSkeleton() {
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <Skeleton className="h-9 w-64" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-72 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [dashboardStats, setDashboardStats] = useState<DashboardStats | null>(
    null,
  );
  const [targets, setTargets] = useState<Target[]>([]);
  const [sweeps, setSweeps] = useState<Sweep[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let active = true;
    Promise.all([api.dashboard(), api.targets(), api.sweeps(), api.findings()])
      .then(([stats, targetList, sweepList, findingList]) => {
        if (!active) return;
        setDashboardStats(stats);
        setTargets(targetList);
        setSweeps(sweepList);
        setFindings(findingList);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.replace("/login");
          return;
        }
        if (active) setError("Failed to load dashboard data.");
      });
    return () => {
      active = false;
    };
  }, [router]);

  const liveSweep = sweeps.find((s) => s.status === "running") ?? sweeps[0];

  if (error) {
    return (
      <div className="mx-auto max-w-6xl rounded-lg border border-destructive/30 bg-destructive/10 p-6 text-sm text-destructive">
        {error}
      </div>
    );
  }

  if (!dashboardStats || !liveSweep) {
    return <DashboardSkeleton />;
  }

  const productionTargets = targets.filter(
    (t) => t.environment === "production",
  ).length;
  const pendingReviewFindings = findings.filter(
    (f) => f.status === "pending_review",
  );
  const CurrentAgentIcon = liveSweep.currentAgent
    ? AGENT_META[liveSweep.currentAgent].icon
    : Radar;

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Security Posture
        </h1>
        <p className="text-sm text-muted-foreground">
          Live view of adversarial testing across your clinical AI fleet.
        </p>
      </div>

      {/* KPI stats */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Targets Monitored"
          value={dashboardStats.targets}
          hint={`${productionTargets} in production`}
          icon={TargetIcon}
        />
        <StatCard
          label="Active Sweeps"
          value={dashboardStats.activeSweeps}
          hint="Running right now"
          icon={Radar}
        />
        <StatCard
          label="Open Findings"
          value={dashboardStats.openFindings}
          hint="Unresolved vulnerabilities"
          icon={ShieldAlert}
        />
        <StatCard
          label="Pending Review"
          value={dashboardStats.pendingReview}
          hint="Critical findings awaiting sign-off"
          icon={ClipboardCheck}
          accent={dashboardStats.pendingReview > 0}
        />
      </div>

      {/* Charts */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Findings by Severity</CardTitle>
            <CardDescription>Distribution across all targets</CardDescription>
          </CardHeader>
          <CardContent>
            <SeverityChart findings={findings} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Findings by Attack Category</CardTitle>
            <CardDescription>Where vulnerabilities cluster</CardDescription>
          </CardHeader>
          <CardContent>
            <CategoryChart findings={findings} />
          </CardContent>
        </Card>
      </div>

      {/* Live sweep + review preview */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Radar className="size-4 text-sky-400" />
              Active Sweep
            </CardTitle>
            <CardDescription>{liveSweep.targetName}</CardDescription>
            <CardAction>
              <CampaignStatusBadge status={liveSweep.status} />
            </CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div>
              <div className="mb-1.5 flex items-center justify-between text-sm">
                <span className="font-medium">{liveSweep.campaignName}</span>
                <span className="tabular-nums text-muted-foreground">
                  {liveSweep.completedCases}/{liveSweep.totalCases} cases
                </span>
              </div>
              <Progress value={liveSweep.progress} />
            </div>
            <div className="flex items-center gap-2 rounded-lg border bg-muted/30 p-3 text-sm">
              <CurrentAgentIcon
                className={cn(
                  "size-4 shrink-0",
                  liveSweep.currentAgent &&
                    AGENT_META[liveSweep.currentAgent].accent,
                )}
              />
              <span className="text-muted-foreground">
                {liveSweep.currentActivity}
              </span>
            </div>
            <div className="flex gap-6 text-sm">
              <div>
                <div className="text-2xl font-semibold tabular-nums text-red-400">
                  {liveSweep.findingsCount}
                </div>
                <div className="text-muted-foreground">Vulnerabilities</div>
              </div>
              <div>
                <div className="text-2xl font-semibold tabular-nums">
                  {liveSweep.progress}%
                </div>
                <div className="text-muted-foreground">Complete</div>
              </div>
            </div>
          </CardContent>
          <CardFooter>
            <Button
              render={<Link href={`/sweeps/${liveSweep.id}`} />}
              nativeButton={false}
              variant="outline"
              className="w-full"
            >
              View live progress
              <ArrowRight className="size-4" />
            </Button>
          </CardFooter>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ClipboardCheck className="size-4 text-amber-400" />
              Awaiting Review
            </CardTitle>
            <CardDescription>
              Critical findings gated before disclosure
            </CardDescription>
            <CardAction>
              <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-sm font-medium tabular-nums text-amber-400">
                {pendingReviewFindings.length}
              </span>
            </CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {pendingReviewFindings.map((finding) => (
              <Link
                key={finding.id}
                href={`/findings/${finding.id}`}
                className="flex items-start gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/50"
              >
                <div className="flex flex-1 flex-col gap-1.5">
                  <span className="text-sm font-medium leading-snug">
                    {finding.title}
                  </span>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <SeverityBadge severity={finding.severity} />
                    <CategoryBadge category={finding.category} short />
                    <span className="text-xs text-muted-foreground">
                      {finding.targetName} · {formatRelativeTime(finding.discoveredAt)}
                    </span>
                  </div>
                </div>
                <ArrowRight className="mt-1 size-4 shrink-0 text-muted-foreground" />
              </Link>
            ))}
          </CardContent>
          <CardFooter>
            <Button
              render={<Link href="/review" />}
              nativeButton={false}
              variant="outline"
              className="w-full"
            >
              Open review queue
              <ArrowRight className="size-4" />
            </Button>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}
