import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi_users import schemas
from pydantic import AfterValidator, BaseModel, Field

from app.discovery.zip_resolver import normalize_zip


# Accepts 12345 or 12345-6789 and stores the first five digits.
ZipCode = Annotated[str, AfterValidator(normalize_zip)]


class UserRead(schemas.BaseUser[uuid.UUID]):
    full_name: str | None = None
    zip_code: str | None = None
    nessie_customer_id: str | None = None


class UserCreate(schemas.BaseUserCreate):
    zip_code: ZipCode


class UserUpdate(schemas.BaseUserUpdate):
    # nessie_customer_id is deliberately absent: only "Connect to bank" sets it.
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    zip_code: ZipCode | None = None


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


class PlaceRef(BaseModel):
    id: int
    level: str
    name: str


class LocationRead(BaseModel):
    zip: str
    method: str
    display_name: str | None  # e.g. "Austin, TX"
    state: PlaceRef | None
    county: PlaceRef | None
    city: PlaceRef | None
    user_confirmed: bool
    alternates: list[PlaceRef]


class LocationUpdate(BaseModel):
    jurisdiction_id: int  # one of the location's alternates


class ProgramRead(BaseModel):
    id: int
    name: str
    jurisdiction: str  # display name, e.g. "Texas" or "Federal"
    level: str
    administering_agency: str | None
    categories: list[str]
    summary: str | None
    eligibility_summary: str | None
    how_to_apply: str | None
    apply_url: str | None
    info_url: str | None
    phone: str | None


class ProgramsForUser(BaseModel):
    location: LocationRead | None
    gathering: list[str]  # areas still being researched, e.g. ["Austin, TX"]
    local: list[ProgramRead]
    federal: list[ProgramRead]
    federal_total: int
