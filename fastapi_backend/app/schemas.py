import uuid
from datetime import date

from fastapi_users import schemas
from pydantic import BaseModel


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class UpcomingBill(BaseModel):
    name: str
    amount: float
    due_date: date


class BalanceRead(BaseModel):
    balance: float
    upcoming_bills: list[UpcomingBill]
    upcoming_bills_total: float
    safe_to_spend: float
