from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.models.enums import (
    AttackCategory,
    FindingStatus,
    OrgPlan,
    Severity,
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


class DashboardStats(CamelModel):
    targets: int
    active_sweeps: int
    open_findings: int
    pending_review: int
