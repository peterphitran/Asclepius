from enum import StrEnum


class AttackCategory(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    IDENTITY_ROLE_EXPLOIT = "identity_role_exploit"
    RAG_POISONING = "rag_poisoning"
    DENIAL_OF_SERVICE = "denial_of_service"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AgentName(StrEnum):
    SELECTOR = "selector"
    GENERATOR = "generator"
    JUDGE = "judge"
    REPORTER = "reporter"


class OrgPlan(StrEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class TargetEnvironment(StrEnum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class TargetHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"


class CampaignStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# SweepStatus is the same set as CampaignStatus (mirrors the frontend alias).


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"


class FindingStatus(StrEnum):
    PUBLISHED = "published"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REMEDIATED = "remediated"
