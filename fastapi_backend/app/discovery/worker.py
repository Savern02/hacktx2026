"""The ingestion worker loop (spec Section 9). All external calls happen here."""

import asyncio
import contextlib
import logging
import os
import socket
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.discovery import queue
from app.discovery.coverage import reresolve_unresolved
from app.discovery.extractor import Extractor, GeminiExtractor
from app.discovery.fetcher import SafeFetcher
from app.discovery.job import JobDeps, run_job
from app.discovery.models import IngestionJob
from app.discovery.serpapi_client import SerpApiClient, SerpApiPaused, _global_pause
from app.discovery.settings import DiscoverySettings

log = logging.getLogger(__name__)

IDLE_SLEEP_S = 5
SWEEP_EVERY_S = 300
PAUSE_RETRY = timedelta(hours=1)

DepsFactory = Callable[[AsyncSession], JobDeps]
SyncHook = Callable[[], Awaitable[object]]


def snowflake_hook(
    settings: DiscoverySettings, sessions: async_sessionmaker[AsyncSession]
) -> SyncHook | None:
    """The Section 16 reporting sync, or None when SNOWFLAKE_ENABLED is false."""
    if not settings.SNOWFLAKE_ENABLED:
        return None
    from app.snowflake import client
    from app.snowflake.sync import check_staleness, run_sync

    connect = client.connector(settings)
    target = client.target(settings)
    interval = timedelta(minutes=settings.SNOWFLAKE_SYNC_INTERVAL_MINUTES)

    async def sync() -> object:
        result = await run_sync(sessions, connect, target)
        async with sessions() as session:
            await check_staleness(session, interval)
        return result

    return sync


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def live_deps_factory(settings: DiscoverySettings) -> DepsFactory:
    settings.require(
        "SERPAPI_API_KEY", "SERPAPI_MONTHLY_BUDGET", "GEMINI_KEY", "FETCH_USER_AGENT"
    )
    assert settings.SERPAPI_API_KEY and settings.SERPAPI_MONTHLY_BUDGET is not None
    assert settings.GEMINI_KEY and settings.FETCH_USER_AGENT
    http = httpx.AsyncClient(timeout=30)
    fetcher = SafeFetcher(settings.FETCH_USER_AGENT)
    extractor: Extractor = GeminiExtractor(
        settings.GEMINI_KEY, settings.EXTRACTION_MODEL, settings.EXTRACTION_MAX_CHARS
    )

    def make(session: AsyncSession) -> JobDeps:
        serp = SerpApiClient(
            session,
            api_key=settings.SERPAPI_API_KEY or "",
            monthly_budget=settings.SERPAPI_MONTHLY_BUDGET or 0,
            reserve=settings.SERPAPI_RESERVE,
            per_job_cap=settings.SERPAPI_MAX_SEARCHES_CITY_JOB,
            http=http,
        )
        return JobDeps(
            serp=serp, fetcher=fetcher, extractor=extractor, settings=settings
        )

    return make


async def _heartbeat_loop(
    sessions: async_sessionmaker[AsyncSession], job_id: int, wid: str
) -> None:
    async with sessions() as hb:
        while True:
            await asyncio.sleep(queue.HEARTBEAT_EVERY_S)
            await queue.heartbeat(hb, job_id, wid)


async def process(
    sessions: async_sessionmaker[AsyncSession],
    job: IngestionJob,
    make_deps: DepsFactory,
    wid: str,
) -> str:
    """Run a claimed job and record its outcome. Returns the job's new status."""
    beat = asyncio.create_task(_heartbeat_loop(sessions, job.id, wid))
    try:
        async with sessions() as session:
            job = await session.get(IngestionJob, job.id) or job
            deps = make_deps(session)
            try:
                outcome = await run_job(session, job, deps)
            except SerpApiPaused as exc:
                await session.rollback()
                until = datetime.now(timezone.utc) + PAUSE_RETRY
                await queue.defer(
                    session,
                    job,
                    until,
                    f"SerpApi paused: {exc}",
                    deps.serp.searches_used,
                )
                return "pending"
            except Exception as exc:
                log.exception("Job %s failed", job.id)
                await session.rollback()
                return await queue.fail(session, job, f"{type(exc).__name__}: {exc}")
            if outcome.deferred_until is not None:
                log.warning(
                    "Job %s deferred until %s: %s",
                    job.id,
                    outcome.deferred_until,
                    outcome.defer_reason,
                )
                await queue.defer(
                    session,
                    job,
                    outcome.deferred_until,
                    outcome.defer_reason or "budget",
                    deps.serp.searches_used,
                )
                return "pending"
            log.info("Job %s succeeded: %s", job.id, outcome.stats)
            return "succeeded"
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat


async def run_forever(
    sessions: async_sessionmaker[AsyncSession],
    make_deps: DepsFactory,
    *,
    once: bool = False,
    snowflake_sync: SyncHook | None = None,
    snowflake_interval: timedelta = timedelta(hours=1),
) -> None:
    wid = worker_id()
    log.info("Worker %s started", wid)
    last_sweep = 0.0
    last_sync = 0.0
    while True:
        if (
            snowflake_sync
            and time.monotonic() - last_sync > snowflake_interval.total_seconds()
        ):
            last_sync = time.monotonic()
            try:
                log.info("Snowflake sync: %s", await snowflake_sync())
            except Exception:  # never let reporting break discovery
                log.exception("Snowflake sync run failed")
        if time.monotonic() - last_sweep > SWEEP_EVERY_S:
            async with sessions() as session:
                reaped = await queue.reap_stale(session)
                fixed = await reresolve_unresolved(session)
            if reaped or fixed:
                log.info(
                    "Sweep: reaped %s stale jobs, re-resolved %s users", reaped, fixed
                )
            last_sweep = time.monotonic()
        if _global_pause["reason"]:
            log.error(
                "SerpApi work paused (%s); fix the key and restart the worker",
                _global_pause["reason"],
            )
            await asyncio.sleep(60)
            continue
        async with sessions() as session:
            job = await queue.claim(session, wid)
        if job is None:
            if once:
                return
            await asyncio.sleep(IDLE_SLEEP_S)
            continue
        log.info(
            "Claimed job %s (jurisdiction %s, %s)",
            job.id,
            job.jurisdiction_id,
            job.job_type,
        )
        await process(sessions, job, make_deps, wid)
        if once:
            return
