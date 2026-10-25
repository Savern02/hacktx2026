"""Seed ~2 months of realistic mock history into a new Nessie account.

Nessie demo accounts start empty, so "Connect to bank" creates a believable,
financially stretched profile: biweekly pay, rent and utilities, an auto loan,
and everyday purchases. Amounts are whole dollars (Nessie stores integers) and
vary slightly per customer (the RNG is seeded with the customer id).
"""

import asyncio
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.finance.models import NessieMerchant
from app.services import nessie_service

HISTORY_DAYS = 60
CONCURRENCY = 8

# name -> Nessie merchant category (the category drives the 50/30/20 bucket).
DEMO_MERCHANTS = {
    "H-E-B": "Groceries",
    "Shell": "Gas",
    "Torchy's Tacos": "Restaurants",
    "Target": "Shopping",
    "Netflix": "Entertainment",
    "CVS Pharmacy": "Pharmacy",
}


@dataclass
class Purchase:
    merchant: str
    day: date
    amount: int
    description: str


def _next_day_of_month(today: date, day: int) -> date:
    candidate = today.replace(day=day)
    if candidate <= today:
        month = today.month % 12 + 1
        candidate = candidate.replace(
            year=today.year + (today.month == 12), month=month
        )
    return candidate


def plan_history(seed: str, today: date) -> dict[str, Any]:
    """Pure: everything that will be written to Nessie, for tests and for seeding."""
    rng = random.Random(seed)
    start = today - timedelta(days=HISTORY_DAYS)
    pay = 1280 + rng.randint(0, 80)

    deposits = []
    day = start + timedelta(days=rng.randint(0, 6))
    while day <= today:
        deposits.append(
            {"day": day, "amount": pay, "description": "Payroll - Direct Deposit"}
        )
        day += timedelta(days=14)

    purchases: list[Purchase] = []

    def every(days: int, merchant: str, low: int, high: int, description: str) -> None:
        d = start + timedelta(days=rng.randint(0, days - 1))
        while d <= today:
            purchases.append(Purchase(merchant, d, rng.randint(low, high), description))
            d += timedelta(days=days + rng.randint(-1, 1))

    every(7, "H-E-B", 72, 112, "Groceries")
    every(7, "Shell", 30, 46, "Gas")
    every(5, "Torchy's Tacos", 16, 38, "Dinner out")
    every(15, "Target", 38, 92, "Household and clothes")
    every(30, "Netflix", 15, 15, "Streaming subscription")
    every(30, "CVS Pharmacy", 12, 30, "Prescriptions")

    bills = [
        {"payee": "Riverside Apartments", "nickname": "Rent", "amount": 1150, "day": 1},
        {
            "payee": "Austin Energy",
            "nickname": "Electric",
            "amount": 82 + rng.randint(0, 30),
            "day": 9,
        },
        {"payee": "T-Mobile", "nickname": "Phone", "amount": 55, "day": 15},
    ]
    for bill in bills:
        bill["next"] = _next_day_of_month(today, bill["day"])

    loan = {
        "type": "auto",
        "monthly_payment": 389,
        "amount": 14200,
        "credit_score": 590 + rng.randint(0, 40),
        # Nessie loans have no rate field; Equa estimates the APR from credit_score.
        "description": "Toyota auto loan",
    }
    return {"deposits": deposits, "purchases": purchases, "bills": bills, "loan": loan}


async def ensure_merchants(session: AsyncSession) -> dict[str, str]:
    """Create the demo merchants in Nessie once; reuse their ids afterwards."""
    known = {
        m.name: m.nessie_id
        for m in (await session.execute(select(NessieMerchant))).scalars()
    }
    for name, category in DEMO_MERCHANTS.items():
        if name not in known:
            known[name] = await nessie_service.create_merchant(name, category)
            session.add(
                NessieMerchant(name=name, category=category, nessie_id=known[name])
            )
    await session.commit()
    return known


async def seed_history(
    session: AsyncSession, customer_id: str, today: date | None = None
) -> dict[str, int]:
    today = today or date.today()
    plan = plan_history(customer_id, today)
    merchants = await ensure_merchants(session)
    account_id = (await nessie_service.checking_account_ids(customer_id))[0]
    limit = asyncio.Semaphore(CONCURRENCY)

    async def create(resource: str, body: dict[str, Any]) -> None:
        async with limit:
            await nessie_service.create_account_resource(account_id, resource, body)

    calls = (
        [
            create(
                "deposits",
                {
                    "medium": "balance",
                    "transaction_date": d["day"].isoformat(),
                    "status": "completed",
                    "amount": d["amount"],
                    "description": d["description"],
                },
            )
            for d in plan["deposits"]
        ]
        + [
            create(
                "purchases",
                {
                    "merchant_id": merchants[p.merchant],
                    "medium": "balance",
                    "purchase_date": p.day.isoformat(),
                    "amount": p.amount,
                    "status": "completed",
                    "description": p.description,
                },
            )
            for p in plan["purchases"]
        ]
        + [
            create(
                "bills",
                {
                    "status": "recurring",
                    "payee": b["payee"],
                    "nickname": b["nickname"],
                    "payment_date": b["next"].isoformat(),
                    "recurring_date": b["day"],
                    "payment_amount": b["amount"],
                },
            )
            for b in plan["bills"]
        ]
        + [
            create("loans", {"status": "approved", **plan["loan"]}),
        ]
    )
    await asyncio.gather(*calls)
    return {k: len(v) if isinstance(v, list) else 1 for k, v in plan.items()}
