from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    # Mock bank customer in Capital One Nessie, created on first balance request.
    nessie_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
