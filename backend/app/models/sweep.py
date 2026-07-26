import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin, UUIDMixin, enum_col
from app.models.campaign import Campaign
from app.models.enums import AgentName, AttackCategory, CampaignStatus, StepStatus


class Sweep(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sweeps"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[CampaignStatus] = mapped_column(
        enum_col(CampaignStatus), default=CampaignStatus.QUEUED
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress: Mapped[int] = mapped_column(default=0)
    total_cases: Mapped[int] = mapped_column(default=0)
    completed_cases: Mapped[int] = mapped_column(default=0)
    findings_count: Mapped[int] = mapped_column(default=0)
    current_agent: Mapped[AgentName | None] = mapped_column(enum_col(AgentName), nullable=True)
    current_activity: Mapped[str | None] = mapped_column(String(500), nullable=True)

    campaign: Mapped[Campaign] = relationship()
    steps: Mapped[list["SweepStep"]] = relationship(
        back_populates="sweep",
        cascade="all, delete-orphan",
        order_by="SweepStep.created_at",
    )


class SweepStep(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sweep_steps"

    sweep_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sweeps.id", ondelete="CASCADE"), index=True
    )
    agent: Mapped[AgentName] = mapped_column(enum_col(AgentName))
    category: Mapped[AttackCategory] = mapped_column(enum_col(AttackCategory))
    strategy: Mapped[str] = mapped_column(String(300))
    status: Mapped[StepStatus] = mapped_column(enum_col(StepStatus), default=StepStatus.PENDING)
    detail: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float | None] = mapped_column(nullable=True)

    sweep: Mapped[Sweep] = relationship(back_populates="steps")
