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
