from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.deps import CurrentUser, SessionDep
from app.models import Finding, Sweep, Target
from app.models.enums import CampaignStatus, FindingStatus
from app.schemas import DashboardStats

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(current_user: CurrentUser, session: SessionDep) -> DashboardStats:
    org_id = current_user.org_id

    targets = await session.scalar(
        select(func.count()).select_from(Target).where(Target.org_id == org_id)
    )
    active_sweeps = await session.scalar(
        select(func.count())
        .select_from(Sweep)
        .where(Sweep.org_id == org_id, Sweep.status == CampaignStatus.RUNNING)
    )
    open_findings = await session.scalar(
        select(func.count())
        .select_from(Finding)
        .where(
            Finding.org_id == org_id,
            Finding.status.notin_([FindingStatus.REJECTED, FindingStatus.REMEDIATED]),
        )
    )
    pending_review = await session.scalar(
        select(func.count())
        .select_from(Finding)
        .where(Finding.org_id == org_id, Finding.status == FindingStatus.PENDING_REVIEW)
    )

    return DashboardStats(
        targets=targets or 0,
        active_sweeps=active_sweeps or 0,
        open_findings=open_findings or 0,
        pending_review=pending_review or 0,
    )
