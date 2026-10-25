import uuid
from datetime import date
from typing import Literal

from fastapi_users import schemas
from pydantic import BaseModel, Field


ZIP_PATTERN = r"^\d{5}$"


class UserRead(schemas.BaseUser[uuid.UUID]):
    full_name: str | None = None
    zip_code: str | None = None
    nessie_customer_id: str | None = None


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    # nessie_customer_id is deliberately absent: only "Connect to bank" sets it.
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    zip_code: str | None = Field(default=None, pattern=ZIP_PATTERN)


class BankConnection(BaseModel):
    nessie_customer_id: str


class UpcomingBill(BaseModel):
    name: str
    amount: float
    due_date: date


class BalanceRead(BaseModel):
    balance: float
    upcoming_bills: list[UpcomingBill]
    upcoming_bills_total: float
    safe_to_spend: float


class ChatMessage(BaseModel):
    role: Literal["user", "equa"]
    text: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)


class ChatResponse(BaseModel):
    reply: str
