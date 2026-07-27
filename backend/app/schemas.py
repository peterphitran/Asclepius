from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.models.enums import (
    AgentName,
    AttackCategory,
    CampaignStatus,
    FindingStatus,
    OrgPlan,
    Severity,
    StepStatus,
    TargetEnvironment,
    TargetHealth,
    UserRole,
)


class CamelModel(BaseModel):
    """Base for API responses: snake_case in Python, camelCase JSON (matches the frontend types)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class Token(BaseModel):
    # OAuth2 convention keeps these snake_case.
    access_token: str
    token_type: str = "bearer"


class OrganizationOut(CamelModel):
    id: UUID
    name: str
    slug: str
    plan: OrgPlan


class UserOut(CamelModel):
    id: UUID
    name: str
    email: str
    role: UserRole
    initials: str


class FindingOut(CamelModel):
    id: UUID
    title: str
    category: AttackCategory
    severity: Severity
    status: FindingStatus
    target_id: UUID
    target_name: str
    sweep_id: UUID | None
    confidence: float
    discovered_at: datetime
    description: str
    patient_safety_impact: str
    reproduction_steps: list[str]
    recommendation: str
    attack_prompt: str
    target_response: str


class TargetOut(CamelModel):
    id: UUID
    name: str
    endpoint: str
    model: str
    environment: TargetEnvironment
    health: TargetHealth
    created_at: datetime
    last_scanned_at: datetime | None
    open_findings: int
    critical_findings: int


class CampaignOut(CamelModel):
    id: UUID
    name: str
    target_id: UUID
    target_name: str
    categories: list[AttackCategory]
    variants_per_case: int
    status: CampaignStatus
    created_at: datetime
    created_by: str


class SweepStepOut(CamelModel):
    id: UUID
    agent: AgentName
    category: AttackCategory
    strategy: str
    status: StepStatus
    detail: str
    confidence: float | None
    timestamp: datetime


class SweepOut(CamelModel):
    id: UUID
    campaign_id: UUID
    campaign_name: str
    target_name: str
    status: CampaignStatus
    started_at: datetime | None
    progress: int
    total_cases: int
    completed_cases: int
    findings_count: int
    current_agent: AgentName | None
    current_activity: str | None
    steps: list[SweepStepOut]


class DashboardStats(CamelModel):
    targets: int
    active_sweeps: int
    open_findings: int
    pending_review: int
