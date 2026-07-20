/**
 * Asclepius domain model.
 *
 * These types are the single source of truth for the shape of data in the UI.
 * They intentionally mirror the entities the backend will persist later
 * (organizations, users, targets, campaigns, sweeps, findings), so the
 * prototype and the real API will speak the same language.
 */

// ---------------------------------------------------------------------------
// Shared enums (modeled as string unions — cheap, type-safe, and serializable)
// ---------------------------------------------------------------------------

/** The five attack families Asclepius runs against a clinical LLM. */
export type AttackCategory =
  | "prompt_injection"
  | "data_exfiltration"
  | "identity_role_exploit"
  | "rag_poisoning"
  | "denial_of_service";

/** Vulnerability severity, ordered from most to least urgent. */
export type Severity = "critical" | "high" | "medium" | "low" | "info";

/** The four agents in the pipeline. */
export type AgentName = "selector" | "generator" | "judge" | "reporter";

// ---------------------------------------------------------------------------
// Tenancy & identity
// ---------------------------------------------------------------------------

export type OrgPlan = "free" | "pro" | "enterprise";

/** A tenant. All other resources are scoped to exactly one organization. */
export interface Organization {
  id: string;
  name: string;
  slug: string;
  plan: OrgPlan;
}

export type UserRole = "owner" | "admin" | "analyst" | "viewer";

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  initials: string;
}

// ---------------------------------------------------------------------------
// Targets — the systems under test
// ---------------------------------------------------------------------------

export type TargetEnvironment = "production" | "staging" | "development";
export type TargetHealth = "healthy" | "degraded" | "unreachable";

/** A clinical AI assistant Asclepius attacks, exposed via a `/chat` endpoint. */
export interface Target {
  id: string;
  name: string;
  endpoint: string;
  model: string;
  environment: TargetEnvironment;
  health: TargetHealth;
  createdAt: string;
  lastScannedAt: string | null;
  openFindings: number;
  criticalFindings: number;
}

// ---------------------------------------------------------------------------
// Campaigns — a configured, repeatable attack run
// ---------------------------------------------------------------------------

export type CampaignStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface Campaign {
  id: string;
  name: string;
  targetId: string;
  targetName: string;
  categories: AttackCategory[];
  variantsPerCase: number;
  status: CampaignStatus;
  createdAt: string;
  createdBy: string;
}

// ---------------------------------------------------------------------------
// Sweeps — a single execution of a campaign, streamed live
// ---------------------------------------------------------------------------

export type SweepStatus = CampaignStatus;
export type StepStatus = "pending" | "running" | "success" | "failure";

/** One line in the live activity feed of a running sweep. */
export interface SweepStep {
  id: string;
  agent: AgentName;
  category: AttackCategory;
  strategy: string;
  status: StepStatus;
  detail: string;
  confidence: number | null;
  timestamp: string;
}

export interface Sweep {
  id: string;
  campaignId: string;
  campaignName: string;
  targetName: string;
  status: SweepStatus;
  startedAt: string;
  progress: number; // 0–100
  totalCases: number;
  completedCases: number;
  findingsCount: number;
  currentAgent: AgentName | null;
  currentActivity: string | null;
  steps: SweepStep[];
}

// ---------------------------------------------------------------------------
// Findings — confirmed vulnerabilities
// ---------------------------------------------------------------------------

export type FindingStatus =
  | "published"
  | "pending_review"
  | "approved"
  | "rejected"
  | "remediated";

export interface Finding {
  id: string;
  title: string;
  category: AttackCategory;
  severity: Severity;
  status: FindingStatus;
  targetId: string;
  targetName: string;
  sweepId: string;
  confidence: number;
  discoveredAt: string;
  description: string;
  patientSafetyImpact: string;
  reproductionSteps: string[];
  recommendation: string;
  attackPrompt: string;
  targetResponse: string;
}
