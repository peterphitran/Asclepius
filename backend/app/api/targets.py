from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, SessionDep
from app.models import Finding, Target
from app.models.enums import FindingStatus, Severity
from app.schemas import TargetOut

router = APIRouter(prefix="/targets", tags=["targets"])

_RESOLVED = [FindingStatus.REJECTED, FindingStatus.REMEDIATED]


async def _finding_counts(
    session: SessionDep, org_id: UUID
) -> tuple[dict[UUID, int], dict[UUID, int]]:
    open_rows = await session.execute(
        select(Finding.target_id, func.count())
        .where(Finding.org_id == org_id, Finding.status.notin_(_RESOLVED))
        .group_by(Finding.target_id)
    )
    crit_rows = await session.execute(
        select(Finding.target_id, func.count())
        .where(
            Finding.org_id == org_id,
            Finding.severity == Severity.CRITICAL,
            Finding.status.notin_(_RESOLVED),
        )
        .group_by(Finding.target_id)
    )
    return dict(open_rows.all()), dict(crit_rows.all())


def _to_out(target: Target, open_findings: int, critical_findings: int) -> TargetOut:
    return TargetOut(
        id=target.id,
        name=target.name,
        endpoint=target.endpoint,
        model=target.model,
        environment=target.environment,
        health=target.health,
        created_at=target.created_at,
        last_scanned_at=target.last_scanned_at,
        open_findings=open_findings,
        critical_findings=critical_findings,
    )


@router.get("", response_model=list[TargetOut])
async def list_targets(current_user: CurrentUser, session: SessionDep) -> list[TargetOut]:
    open_counts, crit_counts = await _finding_counts(session, current_user.org_id)
    result = await session.execute(
        select(Target)
        .where(Target.org_id == current_user.org_id)
        .order_by(Target.created_at.desc())
    )
    return [
        _to_out(t, open_counts.get(t.id, 0), crit_counts.get(t.id, 0))
        for t in result.scalars().all()
    ]


@router.get("/{target_id}", response_model=TargetOut)
async def get_target(
    target_id: UUID, current_user: CurrentUser, session: SessionDep
) -> TargetOut:
    target = await session.get(Target, target_id)
    if target is None or target.org_id != current_user.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target not found")
    open_counts, crit_counts = await _finding_counts(session, current_user.org_id)
    return _to_out(target, open_counts.get(target.id, 0), crit_counts.get(target.id, 0))
