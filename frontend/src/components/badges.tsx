import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  CAMPAIGN_STATUS_META,
  CATEGORY_META,
  FINDING_STATUS_META,
  SEVERITY_META,
  TARGET_HEALTH_META,
} from "@/lib/display";
import type {
  AttackCategory,
  CampaignStatus,
  FindingStatus,
  Severity,
  TargetHealth,
} from "@/lib/types";

export function SeverityBadge({ severity }: { severity: Severity }) {
  const meta = SEVERITY_META[severity];
  return (
    <Badge variant="outline" className={cn("font-medium", meta.badge)}>
      <span className={cn("mr-1.5 size-1.5 rounded-full", meta.dot)} />
      {meta.label}
    </Badge>
  );
}

export function FindingStatusBadge({ status }: { status: FindingStatus }) {
  const meta = FINDING_STATUS_META[status];
  return (
    <Badge variant="outline" className={cn("font-medium", meta.badge)}>
      {meta.label}
    </Badge>
  );
}

export function CampaignStatusBadge({ status }: { status: CampaignStatus }) {
  const meta = CAMPAIGN_STATUS_META[status];
  return (
    <Badge variant="outline" className={cn("font-medium", meta.badge)}>
      {status === "running" && (
        <span className="mr-1.5 size-1.5 animate-pulse rounded-full bg-sky-400" />
      )}
      {meta.label}
    </Badge>
  );
}

export function TargetHealthBadge({ health }: { health: TargetHealth }) {
  const meta = TARGET_HEALTH_META[health];
  return (
    <Badge variant="outline" className={cn("font-medium", meta.badge)}>
      <span className={cn("mr-1.5 size-1.5 rounded-full", meta.dot)} />
      {meta.label}
    </Badge>
  );
}

export function CategoryBadge({
  category,
  short = false,
}: {
  category: AttackCategory;
  short?: boolean;
}) {
  const meta = CATEGORY_META[category];
  const Icon = meta.icon;
  return (
    <Badge variant="secondary" className="font-medium">
      <Icon className="mr-1 size-3" />
      {short ? meta.short : meta.label}
    </Badge>
  );
}
