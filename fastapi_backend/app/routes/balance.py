from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import User
from app.schemas import BalanceRead, BankConnection, UpcomingBill
from app.finance.demo_history import seed_history
from app.services import nessie_service
from app.users import current_active_user

router = APIRouter(tags=["balance"])


LOAN_DUE_DAY = 5  # Nessie loans have no due date; assume the 5th of each month
UPCOMING_WINDOW = timedelta(days=31)


def _next_on_day(today: date, day: int) -> date:
    candidate = today.replace(day=day)
    if candidate < today:
        candidate = (candidate.replace(day=1) + timedelta(days=32)).replace(day=day)
    return candidate


async def get_upcoming_bills(customer_id: str) -> list[UpcomingBill]:
    """Recurring bills and loan payments due in the next month, from Nessie."""
    today = date.today()
    bills: list[UpcomingBill] = []
    for account_id in await nessie_service.checking_account_ids(customer_id):
        for b in await nessie_service.list_account_resource(account_id, "bills"):
            due_raw = b.get("upcoming_payment_date") or b.get("payment_date")
            if b.get("status") not in ("recurring", "pending") or not due_raw:
                continue
            due = date.fromisoformat(due_raw[:10])
            if today <= due <= today + UPCOMING_WINDOW:
                bills.append(
                    UpcomingBill(
                        name=b.get("payee") or b.get("nickname") or "Bill",
                        amount=float(b["payment_amount"]),
                        due_date=due,
                    )
                )
        for loan in await nessie_service.list_account_resource(account_id, "loans"):
            if loan.get("status") == "approved" and loan.get("monthly_payment"):
                bills.append(
                    UpcomingBill(
                        name=loan.get("description")
                        or f"{loan.get('type', 'Loan').title()} loan",
                        amount=float(loan["monthly_payment"]),
                        due_date=_next_on_day(today, LOAN_DUE_DAY),
                    )
                )
    return sorted(bills, key=lambda b: b.due_date)


@router.get("/me/balance", response_model=BalanceRead)
async def get_balance(user: User = Depends(current_active_user)):
    if user.nessie_customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="BANK_NOT_CONNECTED"
        )
    try:
        balance = await nessie_service.get_checking_balance(user.nessie_customer_id)
        bills = await get_upcoming_bills(user.nessie_customer_id)
    except nessie_service.NessieError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    bills_total = round(sum(b.amount for b in bills), 2)
    return BalanceRead(
        balance=balance,
        upcoming_bills=bills,
        upcoming_bills_total=bills_total,
        safe_to_spend=round(balance - bills_total, 2),
    )


@router.post("/me/bank/connect", response_model=BankConnection)
async def connect_bank(
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Create a fresh Nessie customer + checking account for this user (replaces any old one)."""
    if not user.full_name or not user.zip_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="PROFILE_INCOMPLETE"
        )
    first_name, _, last_name = user.full_name.strip().partition(" ")
    try:
        customer_id = await nessie_service.create_demo_customer(
            first_name=first_name, last_name=last_name or "-", zip_code=user.zip_code
        )
        # Fresh demo accounts are empty: seed ~2 months of realistic history.
        await seed_history(session, customer_id)
    except nessie_service.NessieError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    await session.execute(
        update(User).where(User.id == user.id).values(nessie_customer_id=customer_id)
    )
    await session.commit()
    return BankConnection(nessie_customer_id=customer_id)
