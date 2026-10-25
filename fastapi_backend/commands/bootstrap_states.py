"""Queue a discover job for each of the 50 states and DC (priority 50).

    python -m commands.bootstrap_states

Idempotent: re-running bumps request_count on open jobs instead of adding new ones.
WARNING: at 20 searches per state this can use up to 1,020 SerpApi searches.
"""

from sqlalchemy import select, update

from app.discovery.coverage import PRIORITY, enqueue
from app.discovery.models import Jurisdiction, JurisdictionCoverage
from commands._cli import async_session_maker, run


async def main() -> None:
    async with async_session_maker() as session:
        states = (
            (
                await session.execute(
                    select(Jurisdiction.id).where(Jurisdiction.level == "state")
                )
            )
            .scalars()
            .all()
        )
        for state_id in states:
            await enqueue(
                session, state_id, "discover", PRIORITY["bootstrap_state"], "bootstrap"
            )
            await session.execute(
                update(JurisdictionCoverage)
                .where(
                    JurisdictionCoverage.jurisdiction_id == state_id,
                    JurisdictionCoverage.status.in_(["none", "failed"]),
                )
                .values(status="queued")
            )
        await session.commit()
    print(f"Queued {len(states)} state discovery jobs")


if __name__ == "__main__":
    run(main)
