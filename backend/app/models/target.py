import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDMixin, enum_col
from app.models.enums import TargetEnvironment, TargetHealth


class Target(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "targets"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    endpoint: Mapped[str] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(100))
    environment: Mapped[TargetEnvironment] = mapped_column(enum_col(TargetEnvironment))
    health: Mapped[TargetHealth] = mapped_column(
        enum_col(TargetHealth), default=TargetHealth.HEALTHY
    )
    last_scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # openFindings / criticalFindings from the frontend are computed in the API layer.
