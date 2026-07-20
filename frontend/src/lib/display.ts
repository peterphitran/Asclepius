import {
  DatabaseZap,
  FileWarning,
  Gavel,
  type LucideIcon,
  MessageSquareWarning,
  ServerCrash,
  Sparkles,
  Crosshair,
  FileText,
  UserCog,
} from "lucide-react";

import type {
  AgentName,
  AttackCategory,
  CampaignStatus,
  FindingStatus,
  Severity,
  StepStatus,
  TargetHealth,
} from "./types";

// ---------------------------------------------------------------------------
// Attack categories
// ---------------------------------------------------------------------------

export const CATEGORY_META: Record<
  AttackCategory,
  { label: string; short: string; description: string; icon: LucideIcon }
> = {
  prompt_injection: {
    label: "Prompt Injection",
    short: "Injection",
    description:
      "Instructions disguised as user input that override system behavior.",
    icon: MessageSquareWarning,
  },
  data_exfiltration: {
    label: "Data Exfiltration",
    short: "Exfiltration",
    description: "Eliciting patient records or PHI the model shouldn't surface.",
    icon: DatabaseZap,
  },
  identity_role_exploit: {
    label: "Identity & Role Exploits",
    short: "Identity",
    description: "Impersonating roles with elevated privileges.",
    icon: UserCog,
  },
  rag_poisoning: {
    label: "RAG Poisoning",
    short: "RAG",
    description:
      "Adversarial instructions embedded in documents that enter retrieval.",
    icon: FileWarning,
  },
  denial_of_service: {
    label: "Denial of Service",
    short: "DoS",
    description: "Inputs that degrade availability or exhaust context.",
    icon: ServerCrash,
  },
};

export const ALL_CATEGORIES = Object.keys(CATEGORY_META) as AttackCategory[];

// ---------------------------------------------------------------------------
// Severity
// ---------------------------------------------------------------------------

export const SEVERITY_META: Record<
  Severity,
  { label: string; order: number; badge: string; dot: string }
> = {
  critical: {
    label: "Critical",
    order: 0,
    badge: "border-red-500/30 bg-red-500/15 text-red-400",
    dot: "bg-red-500",
  },
  high: {
    label: "High",
    order: 1,
    badge: "border-orange-500/30 bg-orange-500/15 text-orange-400",
    dot: "bg-orange-500",
  },
  medium: {
    label: "Medium",
    order: 2,
    badge: "border-amber-500/30 bg-amber-500/15 text-amber-400",
    dot: "bg-amber-500",
  },
  low: {
    label: "Low",
    order: 3,
    badge: "border-sky-500/30 bg-sky-500/15 text-sky-400",
    dot: "bg-sky-500",
  },
  info: {
    label: "Info",
    order: 4,
    badge: "border-slate-500/30 bg-slate-500/15 text-slate-400",
    dot: "bg-slate-500",
  },
};

export const SEVERITY_ORDER: Severity[] = [
  "critical",
  "high",
  "medium",
  "low",
  "info",
];

// ---------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------

export const AGENT_META: Record<
  AgentName,
  { label: string; icon: LucideIcon; accent: string }
> = {
  selector: { label: "Selector", icon: Crosshair, accent: "text-violet-400" },
  generator: { label: "Generator", icon: Sparkles, accent: "text-sky-400" },
  judge: { label: "Judge", icon: Gavel, accent: "text-amber-400" },
  reporter: { label: "Reporter", icon: FileText, accent: "text-emerald-400" },
};

// ---------------------------------------------------------------------------
// Statuses
// ---------------------------------------------------------------------------

export const CAMPAIGN_STATUS_META: Record<
  CampaignStatus,
  { label: string; badge: string }
> = {
  queued: { label: "Queued", badge: "border-slate-500/30 bg-slate-500/15 text-slate-300" },
  running: { label: "Running", badge: "border-sky-500/30 bg-sky-500/15 text-sky-400" },
  completed: { label: "Completed", badge: "border-emerald-500/30 bg-emerald-500/15 text-emerald-400" },
  failed: { label: "Failed", badge: "border-red-500/30 bg-red-500/15 text-red-400" },
  cancelled: { label: "Cancelled", badge: "border-slate-500/30 bg-slate-500/10 text-slate-400" },
};

export const FINDING_STATUS_META: Record<
  FindingStatus,
  { label: string; badge: string }
> = {
  published: { label: "Published", badge: "border-emerald-500/30 bg-emerald-500/15 text-emerald-400" },
  pending_review: { label: "Pending Review", badge: "border-amber-500/30 bg-amber-500/15 text-amber-400" },
  approved: { label: "Approved", badge: "border-sky-500/30 bg-sky-500/15 text-sky-400" },
  rejected: { label: "Rejected", badge: "border-slate-500/30 bg-slate-500/10 text-slate-400" },
  remediated: { label: "Remediated", badge: "border-violet-500/30 bg-violet-500/15 text-violet-400" },
};

export const STEP_STATUS_META: Record<
  StepStatus,
  { label: string; badge: string; dot: string }
> = {
  pending: { label: "Pending", badge: "border-slate-500/30 bg-slate-500/10 text-slate-400", dot: "bg-slate-500" },
  running: { label: "Running", badge: "border-sky-500/30 bg-sky-500/15 text-sky-400", dot: "bg-sky-500 animate-pulse" },
  success: { label: "Success", badge: "border-red-500/30 bg-red-500/15 text-red-400", dot: "bg-red-500" },
  failure: { label: "Blocked", badge: "border-emerald-500/30 bg-emerald-500/15 text-emerald-400", dot: "bg-emerald-500" },
};

export const TARGET_HEALTH_META: Record<
  TargetHealth,
  { label: string; badge: string; dot: string }
> = {
  healthy: { label: "Healthy", badge: "border-emerald-500/30 bg-emerald-500/15 text-emerald-400", dot: "bg-emerald-500" },
  degraded: { label: "Degraded", badge: "border-amber-500/30 bg-amber-500/15 text-amber-400", dot: "bg-amber-500" },
  unreachable: { label: "Unreachable", badge: "border-red-500/30 bg-red-500/15 text-red-400", dot: "bg-red-500" },
};

/**
 * For an attacker platform, a "successful" step is bad news for the target —
 * so success is rendered in red and a blocked attack in green. This helper
 * keeps that (intentional) inversion in one place.
 */
export function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diffMs = Date.now() - then;
  const min = Math.round(diffMs / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hours = Math.round(min / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
