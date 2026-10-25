"""Money check-up and Equa's program matches for one user, with caching."""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Jurisdiction, Program, UserLocation
from app.finance import advisor, apr
from app.finance.metrics import compute_health, fetch_history
from app.finance.models import FinancialInsight, NessieMerchant, ProgramApplication
from app.models import User
from app.services import nessie_service

HEALTH_TTL = timedelta(hours=1)
RECOMMENDATIONS_TTL = timedelta(hours=24)
MAX_CANDIDATES = 200


class NotConnected(Exception):
    pass


async def get_raw_loans(user: User) -> list[dict[str, Any]]:
    if not user.nessie_customer_id:
        raise NotConnected
    loans: list[dict[str, Any]] = []
    for account_id in await nessie_service.checking_account_ids(
        user.nessie_customer_id
    ):
        loans += await nessie_service.list_account_resource(account_id, "loans")
    return loans


async def get_apr_loans(user: User) -> list[dict[str, Any]]:
    """Approved Nessie loans with their estimated APR, highest first."""
    return apr.summarize_loans(await get_raw_loans(user))


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

    # The user's progress, so Equa's new picks build on what they've done.
    status_rows = await session.execute(
        select(ProgramApplication.program_id, ProgramApplication.status).where(
            ProgramApplication.user_id == user.id
        )
    )
    statuses = {pid: st for pid, st in status_rows.tuples()}
    candidates = [
        {
            "id": p.id,
            "name": p.name,
            "jurisdiction": j.display_name,
            "eligibility": p.eligibility_summary,
            "summary": p.summary,
            "status": statuses.get(p.id),
        }
        for p, j in await visible_programs(session, user)
        # The user said these don't apply to them, so don't suggest them again.
        if statuses.get(p.id) != "not-applicable"
    ]
    result = (
        await advisor.recommend(health, candidates)
        if candidates
        else {"summary": "", "recommendations": []}
    )
    # Keep programs the user already applied to or dismissed, even when Equa
    # doesn't pick them again, so asking again never wipes their progress.
    picked = {r["program_id"] for r in result["recommendations"]}
    previous = (insight.recommendations or {}) if insight else {}
    kept = [
        r
        for r in previous.get("recommendations", [])
        if statuses.get(r["program_id"]) in ("complete", "not-applicable")
        and r["program_id"] not in picked
    ]
    result = {**result, "recommendations": result["recommendations"] + kept}
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
