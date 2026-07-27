from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, SessionDep
from app.models import Campaign
from app.schemas import CampaignOut

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

_LOAD = (selectinload(Campaign.target), selectinload(Campaign.created_by))


def _to_out(campaign: Campaign) -> CampaignOut:
    return CampaignOut(
        id=campaign.id,
        name=campaign.name,
        target_id=campaign.target_id,
        target_name=campaign.target.name,
        categories=campaign.categories,
        variants_per_case=campaign.variants_per_case,
        status=campaign.status,
        created_at=campaign.created_at,
        created_by=campaign.created_by.name if campaign.created_by else "—",
    )


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(current_user: CurrentUser, session: SessionDep) -> list[CampaignOut]:
    result = await session.execute(
        select(Campaign)
        .where(Campaign.org_id == current_user.org_id)
        .options(*_LOAD)
        .order_by(Campaign.created_at.desc())
    )
    return [_to_out(c) for c in result.scalars().all()]


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: UUID, current_user: CurrentUser, session: SessionDep
) -> CampaignOut:
    result = await session.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id, Campaign.org_id == current_user.org_id)
        .options(*_LOAD)
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return _to_out(campaign)
