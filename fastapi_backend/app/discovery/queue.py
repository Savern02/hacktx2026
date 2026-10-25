"""Job queue on ingestion_jobs (spec Section 9): claim, heartbeat, reap, retry, defer."""

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import IngestionJob, JurisdictionCoverage

HEARTBEAT_EVERY_S = 30
STALE_AFTER = timedelta(minutes=15)
REAP_EVERY_S = 300
MAX_BACKOFF = timedelta(hours=6)

CLAIM_SQL = text(
    """
    WITH next AS (
      SELECT id FROM ingestion_jobs
      WHERE status = 'pending' AND run_after <= now()
      ORDER BY priority, run_after, id
      LIMIT 1
      FOR UPDATE SKIP LOCKED
    )
    UPDATE ingestion_jobs j
    SET status = 'running', locked_by = :worker, locked_at = now(), heartbeat_at = now(),
        attempts = j.attempts + 1
    FROM next
    WHERE j.id = next.id
    RETURNING j.id
    """
)


async def claim(session: AsyncSession, worker_id: str) -> IngestionJob | None:
    job_id = await session.scalar(CLAIM_SQL, {"worker": worker_id})
    await session.commit()
    if job_id is None:
        return None
    return await session.get(IngestionJob, job_id, populate_existing=True)


async def heartbeat(session: AsyncSession, job_id: int, worker_id: str) -> None:
    await session.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job_id, IngestionJob.locked_by == worker_id)
        .values(heartbeat_at=datetime.now(timezone.utc))
    )
    await session.commit()


async def reap_stale(session: AsyncSession, now: datetime | None = None) -> int:
    """Running jobs whose worker stopped heartbeating go back to pending."""
    cutoff = (now or datetime.now(timezone.utc)) - STALE_AFTER
    result = await session.execute(
        update(IngestionJob)
        .where(IngestionJob.status == "running", IngestionJob.heartbeat_at < cutoff)
        .values(status="pending", locked_by=None, locked_at=None)
    )
    await session.commit()
    return result.rowcount


def backoff(attempts: int) -> timedelta:
    base = min(timedelta(minutes=5) * (2**attempts), MAX_BACKOFF)
    return base + timedelta(seconds=random.uniform(0, 60))


async def fail(session: AsyncSession, job: IngestionJob, error: str) -> str:
    """Retry with exponential backoff, or mark dead + coverage failed. Returns the new status."""
    now = datetime.now(timezone.utc)
    if job.attempts < job.max_attempts:
        values = {
            "status": "pending",
            "run_after": now + backoff(job.attempts),
            "locked_by": None,
            "locked_at": None,
            "last_error": error[:2000],
        }
    else:
        values = {"status": "dead", "finished_at": now, "last_error": error[:2000]}
        await session.execute(
            update(JurisdictionCoverage)
            .where(JurisdictionCoverage.jurisdiction_id == job.jurisdiction_id)
            .values(status="failed", last_error=error[:2000])
        )
    await session.execute(
        update(IngestionJob).where(IngestionJob.id == job.id).values(**values)
    )
    await session.commit()
    return str(values["status"])


async def defer(
    session: AsyncSession,
    job: IngestionJob,
    until: datetime,
    reason: str,
    searches_used: int,
) -> None:
    """Budget deferral: not a failure, so the attempt it was charged is given back."""
    await session.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job.id)
        .values(
            status="pending",
            run_after=until,
            attempts=IngestionJob.attempts - 1,
            locked_by=None,
            locked_at=None,
            searches_used=searches_used,
            last_error=f"deferred: {reason}",
        )
    )
    await session.commit()
