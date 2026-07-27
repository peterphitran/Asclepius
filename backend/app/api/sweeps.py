from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, SessionDep
from app.models import Campaign, Sweep
from app.schemas import SweepOut, SweepStepOut

router = APIRouter(prefix="/sweeps", tags=["sweeps"])

_LOAD = (
    selectinload(Sweep.campaign).selectinload(Campaign.target),
    selectinload(Sweep.steps),
)


def _to_out(sweep: Sweep) -> SweepOut:
    return SweepOut(
        id=sweep.id,
        campaign_id=sweep.campaign_id,
        campaign_name=sweep.campaign.name,
        target_name=sweep.campaign.target.name,
        status=sweep.status,
        started_at=sweep.started_at,
        progress=sweep.progress,
        total_cases=sweep.total_cases,
        completed_cases=sweep.completed_cases,
        findings_count=sweep.findings_count,
        current_agent=sweep.current_agent,
        current_activity=sweep.current_activity,
        steps=[
            SweepStepOut(
                id=step.id,
                agent=step.agent,
                category=step.category,
                strategy=step.strategy,
                status=step.status,
                detail=step.detail,
                confidence=step.confidence,
                timestamp=step.created_at,
            )
            for step in sweep.steps
        ],
    )


@router.get("", response_model=list[SweepOut])
async def list_sweeps(current_user: CurrentUser, session: SessionDep) -> list[SweepOut]:
    result = await session.execute(
        select(Sweep)
        .where(Sweep.org_id == current_user.org_id)
        .options(*_LOAD)
        .order_by(Sweep.created_at.desc())
    )
    return [_to_out(s) for s in result.scalars().all()]


@router.get("/{sweep_id}", response_model=SweepOut)
async def get_sweep(
    sweep_id: UUID, current_user: CurrentUser, session: SessionDep
) -> SweepOut:
    result = await session.execute(
        select(Sweep)
        .where(Sweep.id == sweep_id, Sweep.org_id == current_user.org_id)
        .options(*_LOAD)
    )
    sweep = result.scalar_one_or_none()
    if sweep is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sweep not found")
    return _to_out(sweep)
