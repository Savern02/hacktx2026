from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(5), nullable=True)
    # Mock bank customer in Capital One Nessie, set by "Connect to bank" in Settings.
    nessie_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)


# Register the program discovery tables on Base.metadata (Alembic + tests).
from app.discovery import models as discovery_models  # noqa: E402, F401
from app.finance import models as finance_models  # noqa: E402, F401
