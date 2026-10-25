import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from fastapi_users.password import PasswordHelper
from sqlalchemy import select, update

from app.discovery import queue
from app.discovery.coverage import check_and_enqueue, save_location_and_enqueue
from app.discovery.models import IngestionJob, JurisdictionCoverage
from app.discovery.zip_resolver import resolve_zip
from app.models import User


async def _user(session, email: str) -> uuid.UUID:
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=PasswordHelper().hash("x"),
        zip_code="78701",
    )
    session.add(user)
    await session.commit()
    return user.id


async def test_concurrent_signups_create_one_job(db_session, geo, sessions):
    a, b = await _user(db_session, "a@x.com"), await _user(db_session, "b@x.com")

    async def signup(user_id):
        async with sessions() as s, s.begin():
            await save_location_and_enqueue(s, user_id, await resolve_zip(s, "78701"))

    await asyncio.gather(signup(a), signup(b))

    jobs = (
        (
            await db_session.execute(
                select(IngestionJob).where(
                    IngestionJob.jurisdiction_id == geo.austin.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1 and jobs[0].request_count == 2
    coverage = await db_session.get(
        JurisdictionCoverage, geo.austin.id, populate_existing=True
    )
    assert (coverage.status, coverage.user_count) == ("queued", 2)


async def test_covered_jurisdiction_enqueues_nothing(db_session, geo):
    await db_session.execute(
        update(JurisdictionCoverage)
        .where(JurisdictionCoverage.jurisdiction_id == geo.austin.id)
        .values(
            status="covered",
            next_refresh_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
    )
    assert await check_and_enqueue(db_session, geo.austin.id, count_user=True) is None


async def test_stale_coverage_enqueues_refresh(db_session, geo):
    await db_session.execute(
        update(JurisdictionCoverage)
        .where(JurisdictionCoverage.jurisdiction_id == geo.austin.id)
        .values(
            status="covered",
            next_refresh_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    job_id = await check_and_enqueue(db_session, geo.austin.id, count_user=True)
    job = await db_session.get(IngestionJob, job_id)
    assert (job.job_type, job.priority) == ("refresh", 100)


async def test_not_applicable_enqueues_nothing(db_session, geo):
    assert (
        await check_and_enqueue(db_session, geo.hudson_bend.id, count_user=True) is None
    )


async def _job(session, jurisdiction_id: int, **values) -> IngestionJob:
    job = IngestionJob(
        jurisdiction_id=jurisdiction_id,
        job_type="discover",
        triggered_by="admin",
        **values,
    )
    session.add(job)
    await session.commit()
    return job


async def test_two_workers_never_claim_the_same_job(db_session, geo, sessions):
    await _job(db_session, geo.austin.id)
    await _job(db_session, geo.texas.id)

    async def worker(name):
        async with sessions() as s:
            job = await queue.claim(s, name)
            return job.id if job else None

    claimed = await asyncio.gather(worker("w1"), worker("w2"), worker("w3"))
    got = [c for c in claimed if c is not None]
    assert len(got) == 2 and len(set(got)) == 2


async def test_reaper_reclaims_stale_heartbeat(db_session, geo):
    job = await _job(db_session, geo.austin.id)
    claimed = await queue.claim(db_session, "w1")
    assert claimed.id == job.id
    later = datetime.now(timezone.utc) + timedelta(minutes=16)
    assert await queue.reap_stale(db_session, now=later) == 1
    refreshed = await db_session.get(IngestionJob, job.id, populate_existing=True)
    assert refreshed.status == "pending" and refreshed.locked_by is None


async def test_budget_deferral_does_not_consume_an_attempt(db_session, geo):
    await _job(db_session, geo.austin.id)
    job = await queue.claim(db_session, "w1")
    assert job.attempts == 1
    until = datetime.now(timezone.utc) + timedelta(hours=1)
    await queue.defer(
        db_session, job, until, "hourly throughput at 90%", searches_used=3
    )
    job = await db_session.get(IngestionJob, job.id, populate_existing=True)
    assert (job.status, job.attempts, job.searches_used) == ("pending", 0, 3)
    assert job.run_after >= until - timedelta(seconds=1)


async def test_job_goes_dead_after_max_attempts(db_session, geo):
    await _job(db_session, geo.austin.id, max_attempts=2)
    for expected in ("pending", "dead"):
        await db_session.execute(
            update(IngestionJob).values(
                run_after=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        )
        await db_session.commit()
        job = await queue.claim(db_session, "w1")
        assert await queue.fail(db_session, job, "boom") == expected
    coverage = await db_session.get(
        JurisdictionCoverage, geo.austin.id, populate_existing=True
    )
    assert (coverage.status, coverage.last_error) == ("failed", "boom")
