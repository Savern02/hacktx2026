from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models import User
from app.schemas import BalanceRead, UpcomingBill
from app.services import nessie_service
from app.users import current_active_user

router = APIRouter(tags=["balance"])


def get_upcoming_bills() -> list[UpcomingBill]:
    # Hardcoded until bills are detected from Nessie transactions.
    today = date.today()
    return [
        UpcomingBill(
            name="Toyota auto loan", amount=389.00, due_date=today + timedelta(days=5)
        ),
        UpcomingBill(
            name="Austin Energy", amount=96.50, due_date=today + timedelta(days=9)
        ),
    ]


@router.get("/me/balance", response_model=BalanceRead)
async def get_balance(
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    try:
        customer_id = user.nessie_customer_id
        if customer_id is None:
            customer_id = await nessie_service.create_demo_customer(
                first_name=user.email.split("@")[0], last_name="Demo"
            )
            await session.execute(
                update(User)
                .where(User.id == user.id)
                .values(nessie_customer_id=customer_id)
            )
            await session.commit()
        balance = await nessie_service.get_checking_balance(customer_id)
    except nessie_service.NessieError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    bills = get_upcoming_bills()
    bills_total = round(sum(b.amount for b in bills), 2)
    return BalanceRead(
        balance=balance,
        upcoming_bills=bills,
        upcoming_bills_total=bills_total,
        safe_to_spend=round(balance - bills_total, 2),
    )
