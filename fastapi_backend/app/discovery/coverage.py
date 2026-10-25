"""Save a user's location, then check coverage and enqueue discovery (spec Section 8)."""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import JurisdictionCoverage, UserLocation
from app.discovery.settings import discovery_settings
from app.discovery.zip_resolver import Resolution, resolve_with_timeout

log = logging.getLogger(__name__)

PRIORITY = {
    "admin": 5,
    "signup": 10,
    "bootstrap_state": 50,
    "bootstrap_city": 60,
    "refresh": 100,
}

ENQUEUE_SQL = text(
    """
    INSERT INTO ingestion_jobs (jurisdiction_id, job_type, priority, triggered_by)
    VALUES (:jurisdiction_id, :job_type, :priority, :triggered_by)
    ON CONFLICT (jurisdiction_id, job_type) WHERE status IN ('pending','running')
    DO UPDATE SET request_count = ingestion_jobs.request_count + 1,
                  priority      = LEAST(ingestion_jobs.priority, EXCLUDED.priority)
    RETURNING id
    """
)


async def enqueue(
    session: AsyncSession,
    jurisdiction_id: int,
    job_type: str,
    priority: int,
    triggered_by: str,
) -> int:
    job_id = await session.scalar(
        ENQUEUE_SQL,
        {
            "jurisdiction_id": jurisdiction_id,
            "job_type": job_type,
            "priority": priority,
            "triggered_by": triggered_by,
        },
    )
    assert job_id is not None
    return job_id


async def check_and_enqueue(
    session: AsyncSession, jurisdiction_id: int, *, count_user: bool
) -> int | None:
    """Apply the Section 8 table to one jurisdiction. Returns the job id if one was (re)queued."""
    # Upsert the coverage row and bump user_count atomically; the row lock this
    # takes serialises concurrent signups for the same jurisdiction.
    status, next_refresh_at = (
        await session.execute(
            insert(JurisdictionCoverage)
            .values(
                jurisdiction_id=jurisdiction_id,
                status="none",
                user_count=1 if count_user else 0,
            )
            .on_conflict_do_update(
                index_elements=["jurisdiction_id"],
                set_={
                    "user_count": JurisdictionCoverage.user_count
                    + (1 if count_user else 0)
                },
            )
            .returning(
                JurisdictionCoverage.status, JurisdictionCoverage.next_refresh_at
            )
        )
    ).one()

    if status in ("none", "failed", "queued", "in_progress"):
        job_id = await enqueue(
            session, jurisdiction_id, "discover", PRIORITY["signup"], "signup"
        )
        if status in ("none", "failed"):
            await session.execute(
                update(JurisdictionCoverage)
                .where(JurisdictionCoverage.jurisdiction_id == jurisdiction_id)
                .values(status="queued")
            )
        return job_id

    if status in ("covered", "covered_empty", "awaiting_review"):
        if next_refresh_at is not None and next_refresh_at <= datetime.now(
            timezone.utc
        ):
            return await enqueue(
                session, jurisdiction_id, "refresh", PRIORITY["refresh"], "signup"
            )
    return None  # not_applicable, or covered and fresh


def _jurisdictions_to_check(resolution: Resolution) -> list[int]:
    ids = [resolution.state_id, resolution.local_id]
    if discovery_settings.ENABLE_COUNTY_DISCOVERY and resolution.city_id:
        ids.append(resolution.county_id)
    return list(dict.fromkeys(i for i in ids if i is not None))


async def save_location_and_enqueue(
    session: AsyncSession, user_id: uuid.UUID, resolution: Resolution
) -> UserLocation:
    """Write user_locations, then run coverage checks, in the caller's transaction.

    A user-confirmed location for the same ZIP is never overwritten by automatic
    re-resolution. user_count only counts jurisdictions the user newly joins.
    """
    existing = await session.get(UserLocation, user_id, with_for_update=True)
    previous: set[int] = set()
    if existing is not None:
        if existing.user_confirmed and existing.zip == resolution.zip:
            return existing
        previous = {
            i
            for i in (existing.state_id, existing.county_id, existing.city_id)
            if i is not None
        }

    values = {
        "zip": resolution.zip,
        "state_id": resolution.state_id,
        "county_id": resolution.county_id,
        "city_id": resolution.city_id,
        "method": resolution.method,
        "confidence": resolution.confidence,
        "alternates": resolution.alternates,
        "user_confirmed": False,
        "resolved_at": datetime.now(timezone.utc),
    }
    await session.execute(
        insert(UserLocation)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(index_elements=["user_id"], set_=values)
    )
    for jurisdiction_id in _jurisdictions_to_check(resolution):
        await check_and_enqueue(
            session, jurisdiction_id, count_user=jurisdiction_id not in previous
        )
    location = await session.get(UserLocation, user_id, populate_existing=True)
    assert location is not None
    return location


async def on_zip_saved(
    session: AsyncSession, user_id: uuid.UUID, zip_code: str
) -> None:
    """Signup / Settings hook. Never raises: a failure must not break the request.

    Resolution runs on its own connection so a timeout can't poison the caller's.
    """
    engine = session.bind
    try:
        async with AsyncSession(bind=engine, expire_on_commit=False) as own:
            async with own.begin():
                resolution = await resolve_with_timeout(own, zip_code)
                await save_location_and_enqueue(own, user_id, resolution)
    except Exception:
        log.exception("Location / coverage update failed for user %s", user_id)


async def reresolve_unresolved(session: AsyncSession, limit: int = 200) -> int:
    """Worker sweep: retry users left 'unresolved' (timeout, or ZIP data loaded later)."""
    rows = (
        await session.execute(
            select(UserLocation.user_id, UserLocation.zip)
            .where(
                UserLocation.method == "unresolved",
                UserLocation.user_confirmed.is_(False),
            )
            .limit(limit)
        )
    ).all()
    fixed = 0
    for user_id, zip_code in rows:
        resolution = await resolve_with_timeout(session, zip_code, timeout=5)
        if resolution.method != "unresolved":
            await save_location_and_enqueue(session, user_id, resolution)
            fixed += 1
    await session.commit()
    return fixed
