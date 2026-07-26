import uuid

from sqlalchemy import ARRAY, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin, UUIDMixin, enum_col
from app.models.enums import CampaignStatus
from app.models.target import Target
from app.models.tenancy import User


class Campaign(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), index=True
    )
    # Stores AttackCategory values; validated against the enum in the API layer.
    categories: Mapped[list[str]] = mapped_column(ARRAY(String(50)))
    variants_per_case: Mapped[int] = mapped_column(default=6)
    status: Mapped[CampaignStatus] = mapped_column(
        enum_col(CampaignStatus), default=CampaignStatus.QUEUED
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    target: Mapped[Target] = relationship()
    created_by: Mapped[User | None] = relationship()
