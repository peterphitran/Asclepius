from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, SessionDep
from app.models import Finding
from app.schemas import FindingOut

router = APIRouter(prefix="/findings", tags=["findings"])


def finding_to_out(finding: Finding) -> FindingOut:
    return FindingOut(
        id=finding.id,
        title=finding.title,
        category=finding.category,
        severity=finding.severity,
        status=finding.status,
        target_id=finding.target_id,
        target_name=finding.target.name,
        sweep_id=finding.sweep_id,
        confidence=finding.confidence,
        discovered_at=finding.discovered_at,
        description=finding.description,
        patient_safety_impact=finding.patient_safety_impact,
        reproduction_steps=finding.reproduction_steps,
        recommendation=finding.recommendation,
        attack_prompt=finding.attack_prompt,
        target_response=finding.target_response,
    )


@router.get("", response_model=list[FindingOut])
async def list_findings(current_user: CurrentUser, session: SessionDep) -> list[FindingOut]:
    result = await session.execute(
        select(Finding)
        .where(Finding.org_id == current_user.org_id)
        .options(selectinload(Finding.target))
        .order_by(Finding.discovered_at.desc())
    )
    return [finding_to_out(f) for f in result.scalars().all()]


@router.get("/{finding_id}", response_model=FindingOut)
async def get_finding(
    finding_id: UUID, current_user: CurrentUser, session: SessionDep
) -> FindingOut:
    result = await session.execute(
        select(Finding)
        .where(Finding.id == finding_id, Finding.org_id == current_user.org_id)
        .options(selectinload(Finding.target))
    )
    finding = result.scalar_one_or_none()
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    return finding_to_out(finding)
