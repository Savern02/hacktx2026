"""Money check-up and Equa's program matches for one user, with caching."""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Jurisdiction, Program, UserLocation
from app.finance import advisor
from app.finance.metrics import compute_health, fetch_history
from app.finance.models import FinancialInsight, NessieMerchant
from app.models import User

HEALTH_TTL = timedelta(hours=1)
RECOMMENDATIONS_TTL = timedelta(hours=24)
MAX_CANDIDATES = 200


class NotConnected(Exception):
    pass


async def _insight(session: AsyncSession, user: User) -> FinancialInsight | None:
    insight = await session.get(FinancialInsight, user.id)
    if insight and insight.nessie_customer_id != user.nessie_customer_id:
        return None  # bank was reconnected: the cache belongs to the old account
    return insight


async def get_health(
    session: AsyncSession, user: User, refresh: bool = False
) -> dict[str, Any]:
    if not user.nessie_customer_id:
        raise NotConnected
    now = datetime.now(timezone.utc)
    insight = await _insight(session, user)
    if insight and not refresh and now - insight.health_at < HEALTH_TTL:
        return insight.health

    known = {
        m.nessie_id: m.category
        for m in (await session.execute(select(NessieMerchant))).scalars()
    }
    history = await fetch_history(user.nessie_customer_id, known)
    health = compute_health(history, date.today().isoformat())

    values = {
        "nessie_customer_id": user.nessie_customer_id,
        "health": health,
        "health_at": now,
    }
    stale_recs = insight is None  # a new bank means old matches no longer apply
    if stale_recs:
        values |= {"recommendations": None, "recommendations_at": None}
    await session.execute(
        insert(FinancialInsight)
        .values(user_id=user.id, **values)
        .on_conflict_do_update(index_elements=["user_id"], set_=values)
    )
    await session.commit()
    return health


async def visible_programs(
    session: AsyncSession, user: User
) -> list[tuple[Program, Jurisdiction]]:
    """Programs this user can see: federal, plus their state, county and city."""
    loc = await session.get(UserLocation, user.id)
    federal_id = await session.scalar(
        select(Jurisdiction.id).where(Jurisdiction.level == "federal")
    )
    ids = [
        i
        for i in (
            federal_id,
            *((loc.state_id, loc.county_id, loc.city_id) if loc else ()),
        )
        if i
    ]
    rows = await session.execute(
        select(Program, Jurisdiction)
        .join(Jurisdiction, Jurisdiction.id == Program.jurisdiction_id)
        .where(
            Program.jurisdiction_id.in_(ids),
            Program.review_status == "published",
            Program.status == "active",
            Program.audience == "individual",
            or_(Program.summary.is_not(None), Program.eligibility_summary.is_not(None)),
        )
        .order_by(Jurisdiction.level.desc(), Program.name)  # local programs first
        .limit(MAX_CANDIDATES)
    )
    return list(rows.tuples().all())


async def get_recommendations(
    session: AsyncSession, user: User, refresh: bool = False
) -> dict[str, Any]:
    health = await get_health(session, user)
    now = datetime.now(timezone.utc)
    insight = await _insight(session, user)
    if (
        insight
        and insight.recommendations
        and insight.recommendations_at
        and not refresh
        and now - insight.recommendations_at < RECOMMENDATIONS_TTL
    ):
        return insight.recommendations | {
            "computed_at": insight.recommendations_at.isoformat()
        }

    candidates = [
        {
            "id": p.id,
            "name": p.name,
            "jurisdiction": j.display_name,
            "eligibility": p.eligibility_summary,
            "summary": p.summary,
        }
        for p, j in await visible_programs(session, user)
    ]
    result = (
        await advisor.recommend(health, candidates)
        if candidates
        else {"summary": "", "recommendations": []}
    )
    await session.execute(
        insert(FinancialInsight)
        .values(
            user_id=user.id,
            nessie_customer_id=user.nessie_customer_id,
            health=health,
            recommendations=result,
            recommendations_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={"recommendations": result, "recommendations_at": now},
        )
    )
    await session.commit()
    return result | {"computed_at": now.isoformat()}
