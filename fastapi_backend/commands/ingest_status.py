"""Queue, coverage and SerpApi usage at a glance.

    python -m commands.ingest_status
"""

from sqlalchemy import func, select

from app.discovery.models import (
    IngestionJob,
    Jurisdiction,
    JurisdictionCoverage,
    Program,
    SerpApiRequest,
)
from commands._cli import async_session_maker, run


async def main() -> None:
    async with async_session_maker() as session:
        print("Jobs by status:")
        for status, count in await session.execute(
            select(IngestionJob.status, func.count()).group_by(IngestionJob.status)
        ):
            print(f"  {status:<10} {count}")
        print("\nOpen and recent jobs:")
        rows = await session.execute(
            select(IngestionJob, Jurisdiction.display_name)
            .join(Jurisdiction, Jurisdiction.id == IngestionJob.jurisdiction_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(15)
        )
        for job, name in rows:
            print(
                f"  #{job.id:<5} {job.status:<9} p{job.priority:<3} {job.job_type:<8} {name:<28} req={job.request_count} searches={job.searches_used} attempts={job.attempts} {job.last_error or ''}"
            )
        print("\nCoverage (non-default):")
        for status, count in await session.execute(
            select(JurisdictionCoverage.status, func.count())
            .where(JurisdictionCoverage.status.not_in(["none", "not_applicable"]))
            .group_by(JurisdictionCoverage.status)
        ):
            print(f"  {status:<16} {count}")
        print("\nPrograms by review status:")
        for status, count in await session.execute(
            select(Program.review_status, func.count()).group_by(Program.review_status)
        ):
            print(f"  {status:<13} {count}")
        searches = await session.scalar(
            select(func.count())
            .select_from(SerpApiRequest)
            .where(SerpApiRequest.http_status == 200)
        )
        print(f"\nSerpApi searches logged: {searches}")


if __name__ == "__main__":
    run(main)
