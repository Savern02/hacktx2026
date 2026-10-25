"""Tables for Nessie-based financial health (user-level: never synced to Snowflake)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class NessieMerchant(Base):
    """Demo merchants created once in Nessie and reused for every seeded history."""

    __tablename__ = "nessie_merchants"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(Text)
    nessie_id: Mapped[str] = mapped_column(Text)


class FinancialInsight(Base):
    """Cached 50/30/20 + 28/36 check-up and Equa's program matches for one user."""

    __tablename__ = "financial_insights"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    nessie_customer_id: Mapped[str] = mapped_column(Text)
    health: Mapped[dict[str, Any]] = mapped_column(JSONB)
    health_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    recommendations: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recommendations_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
