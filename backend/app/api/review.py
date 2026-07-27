from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.findings import finding_to_out
from app.core.deps import CurrentUser, SessionDep
from app.models import Finding
from app.models.enums import FindingStatus
from app.schemas import FindingOut

router = APIRouter(prefix="/review", tags=["review"])


@router.get("", response_model=list[FindingOut])
async def list_review_queue(
    current_user: CurrentUser, session: SessionDep
) -> list[FindingOut]:
    """Findings gated for human review before disclosure."""
    result = await session.execute(
        select(Finding)
        .where(
            Finding.org_id == current_user.org_id,
            Finding.status == FindingStatus.PENDING_REVIEW,
        )
        .options(selectinload(Finding.target))
        .order_by(Finding.discovered_at.desc())
    )
    return [finding_to_out(f) for f in result.scalars().all()]
