"""Load the federal row, states, counties, places and coverage rows.

    python -m commands.load_geography

Idempotent: safe to re-run; it upserts and never duplicates rows.
"""

from app.discovery import geography
from commands._cli import async_session_maker, download_text, run


async def main() -> None:
    states = download_text(geography.STATE_URL, "2024_Gaz_state_national.txt")
    counties = download_text(geography.COUNTY_URL, "2024_Gaz_counties_national.txt")
    places = download_text(geography.PLACE_URL, "national_place2020.txt")
    async with async_session_maker() as session:
        counts = await geography.load_geography(session, states, counties, places)
    print(f"Loaded {counts}")


if __name__ == "__main__":
    run(main)
