import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin, UUIDMixin, enum_col
from app.models.enums import AttackCategory, FindingStatus, Severity
from app.models.sweep import Sweep
from app.models.target import Target


class Finding(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "findings"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[AttackCategory] = mapped_column(enum_col(AttackCategory))
    severity: Mapped[Severity] = mapped_column(enum_col(Severity))
    status: Mapped[FindingStatus] = mapped_column(
        enum_col(FindingStatus), default=FindingStatus.PENDING_REVIEW
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), index=True
    )
    sweep_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sweeps.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float]
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    description: Mapped[str] = mapped_column(Text)
    patient_safety_impact: Mapped[str] = mapped_column(Text)
    reproduction_steps: Mapped[list[str]] = mapped_column(ARRAY(String(500)))
    recommendation: Mapped[str] = mapped_column(Text)
    attack_prompt: Mapped[str] = mapped_column(Text)
    target_response: Mapped[str] = mapped_column(Text)

    target: Mapped[Target] = relationship()
    sweep: Mapped[Sweep | None] = relationship()
