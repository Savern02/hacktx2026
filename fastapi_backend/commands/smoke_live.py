"""Manual live smoke test: resolve a ZIP and run a tiny real discovery job.

    ALLOW_LIVE_SMOKE=1 python -m commands.smoke_live --zip 78701

Refuses to run without ALLOW_LIVE_SMOKE=1 and stops after 3 SerpApi searches.
Uses the dev database; replayed searches (last 30 days) cost nothing.
"""

import argparse

from sqlalchemy import select

from app.discovery.job import run_job
from app.discovery.models import IngestionJob
from app.discovery.coverage import PRIORITY, enqueue
from app.discovery.worker import live_deps_factory
from app.discovery.zip_resolver import resolve_zip
from commands._cli import async_session_maker, discovery_settings, run

MAX_SEARCHES = 3


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True)
    args = parser.parse_args()
    if not discovery_settings.ALLOW_LIVE_SMOKE:
        raise SystemExit(
            "Refusing to run: set ALLOW_LIVE_SMOKE=1 to allow live API calls."
        )

    settings = discovery_settings.model_copy(
        update={
            "SERPAPI_MAX_SEARCHES_CITY_JOB": MAX_SEARCHES,
            "SERPAPI_MAX_SEARCHES_STATE_JOB": MAX_SEARCHES,
            "MAX_PAGES_PER_JOB": 5,
        }
    )
    make_deps = live_deps_factory(settings)
    async with async_session_maker() as session:
        resolution = await resolve_zip(session, args.zip)
        print(
            f"ZIP {resolution.zip}: {resolution.method} (confidence {resolution.confidence})"
        )
        target = resolution.local_id or resolution.state_id
        if target is None:
            raise SystemExit(
                "ZIP is unresolved; nothing to discover (federal programs only)."
            )
        job_id = await enqueue(session, target, "discover", PRIORITY["admin"], "admin")
        await session.commit()
        job = await session.get(IngestionJob, job_id)
        assert job is not None
        job.status, job.attempts = "running", job.attempts + 1
        await session.commit()
        deps = make_deps(session)
        deps.serp.per_job_cap = MAX_SEARCHES
        outcome = await run_job(session, job, deps)
        job = await session.scalar(
            select(IngestionJob)
            .where(IngestionJob.id == job_id)
            .execution_options(populate_existing=True)
        )
        assert job is not None
        print(
            f"Job #{job.id}: {job.status}, searches used {deps.serp.searches_used}/{MAX_SEARCHES}"
        )
        print(
            outcome.stats
            if outcome.deferred_until is None
            else f"Deferred: {outcome.defer_reason}"
        )


if __name__ == "__main__":
    run(main)
