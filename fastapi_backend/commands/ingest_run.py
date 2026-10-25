"""Queue an admin-priority discover job for one jurisdiction by Census GEOID.

    python -m commands.ingest_run --geoid 4805000          # Austin city
    python -m commands.ingest_run --geoid 48 --level state  # Texas

The worker picks it up next (priority 5).
"""

import argparse

from sqlalchemy import select, update

from app.discovery.coverage import PRIORITY, enqueue
from app.discovery.models import Jurisdiction, JurisdictionCoverage
from commands._cli import async_session_maker, run

LEVEL_BY_LENGTH = {2: "state", 5: "county", 7: "city"}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geoid", required=True)
    parser.add_argument("--level", choices=["state", "county", "city"])
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    level = args.level or LEVEL_BY_LENGTH.get(len(args.geoid))
    async with async_session_maker() as session:
        j = await session.scalar(
            select(Jurisdiction).where(
                Jurisdiction.geoid == args.geoid, Jurisdiction.level == level
            )
        )
        if j is None:
            raise SystemExit(f"No {level} with GEOID {args.geoid}")
        job_id = await enqueue(
            session,
            j.id,
            "refresh" if args.refresh else "discover",
            PRIORITY["admin"],
            "admin",
        )
        await session.execute(
            update(JurisdictionCoverage)
            .where(
                JurisdictionCoverage.jurisdiction_id == j.id,
                JurisdictionCoverage.status.in_(["none", "failed"]),
            )
            .values(status="queued")
        )
        await session.commit()
    print(f"Queued job #{job_id} for {j.display_name}")


if __name__ == "__main__":
    run(main)
