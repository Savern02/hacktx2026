"""Reference geography (spec Section 6): federal row, states, counties, places.

Sources (all public, no key):
- States and counties: Census 2024 Gazetteer files (tab-delimited).
- Places: Census 2020 national place code file (pipe-delimited). The Gazetteer
  place file has no CLASSFP, and 2020 place GEOIDs match the 2020 ZCTA-place
  relationship file used by the ZIP resolver.
"""

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Jurisdiction, JurisdictionCoverage
from app.discovery.normalize import place_display_name

GAZETTEER_BASE = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer"
)
STATE_URL = f"{GAZETTEER_BASE}/2024_Gaz_state_national.zip"
COUNTY_URL = f"{GAZETTEER_BASE}/2024_Gaz_counties_national.zip"
PLACE_URL = (
    "https://www2.census.gov/geo/docs/reference/codes2020/national_place2020.txt"
)

# v1 scope is the 50 states and DC: territories resolve as 'unresolved'.
TERRITORY_FIPS = {"60", "66", "69", "72", "74", "78"}


@dataclass(frozen=True)
class GeoRow:
    level: str
    geoid: str
    name: str
    display_name: str
    state_code: str
    place_class: str | None = None
    is_incorporated: bool | None = None


def _rows(data: str, delimiter: str) -> Iterable[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(data.lstrip("﻿")), delimiter=delimiter)
    for row in reader:
        # Gazetteer headers carry trailing whitespace on the last column.
        yield {k.strip(): (v or "").strip() for k, v in row.items() if k}


def parse_states(data: str) -> list[GeoRow]:
    return [
        GeoRow("state", r["GEOID"], r["NAME"], r["NAME"], r["USPS"])
        for r in _rows(data, "\t")
        if r["GEOID"] not in TERRITORY_FIPS
    ]


def parse_counties(data: str) -> list[GeoRow]:
    return [
        GeoRow("county", r["GEOID"], r["NAME"], f"{r['NAME']}, {r['USPS']}", r["USPS"])
        for r in _rows(data, "\t")
        if r["GEOID"][:2] not in TERRITORY_FIPS
    ]


def is_incorporated_class(classfp: str) -> bool:
    # C* = incorporated place; C9 = inactive/nonfunctioning incorporated place
    # (no working city government). U1/U2 = CDPs, M2 = military installations.
    return classfp.startswith("C") and classfp != "C9"


def parse_places(data: str) -> list[GeoRow]:
    rows = []
    for r in _rows(data, "|"):
        if r["STATEFP"] in TERRITORY_FIPS:
            continue
        classfp = r["CLASSFP"]
        rows.append(
            GeoRow(
                "city",
                r["STATEFP"] + r["PLACEFP"],
                r["PLACENAME"],
                place_display_name(r["PLACENAME"], r["STATE"]),
                r["STATE"],
                place_class=classfp,
                is_incorporated=is_incorporated_class(classfp),
            )
        )
    return rows


async def ensure_federal(session: AsyncSession) -> int:
    await session.execute(
        insert(Jurisdiction)
        .values(level="federal", name="United States", display_name="Federal")
        .on_conflict_do_nothing(
            index_elements=["level"], index_where=text("level = 'federal'")
        )
    )
    federal_id = await session.scalar(
        select(Jurisdiction.id).where(Jurisdiction.level == "federal")
    )
    assert federal_id is not None
    return federal_id


async def upsert_jurisdictions(
    session: AsyncSession, rows: list[GeoRow], parent_by_state: dict[str, int] | None
) -> None:
    """parent_by_state maps USPS code -> state id; None means parent is the federal row."""
    federal_id = await ensure_federal(session)
    values = [
        {
            "level": r.level,
            "geoid": r.geoid,
            "name": r.name,
            "display_name": r.display_name,
            "state_code": r.state_code,
            "parent_id": federal_id
            if parent_by_state is None
            else parent_by_state.get(r.state_code),
            "place_class": r.place_class,
            "is_incorporated": r.is_incorporated,
        }
        for r in rows
    ]
    for start in range(0, len(values), 2000):
        stmt = insert(Jurisdiction).values(values[start : start + 2000])
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="jurisdictions_level_geoid",
                set_={
                    c: stmt.excluded[c]
                    for c in (
                        "name",
                        "display_name",
                        "state_code",
                        "parent_id",
                        "place_class",
                        "is_incorporated",
                    )
                },
            )
        )


async def state_ids(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        select(Jurisdiction.state_code, Jurisdiction.id).where(
            Jurisdiction.level == "state"
        )
    )
    return {code: jid for code, jid in result.all() if code}


async def ensure_coverage_rows(session: AsyncSession) -> None:
    """One coverage row per jurisdiction. Existing statuses are never overwritten."""
    await session.execute(
        insert(JurisdictionCoverage)
        .from_select(
            ["jurisdiction_id", "status"],
            select(
                Jurisdiction.id,
                text(
                    "CASE WHEN level = 'city' AND is_incorporated IS NOT TRUE "
                    "THEN 'not_applicable' ELSE 'none' END"
                ),
            ),
        )
        .on_conflict_do_nothing(index_elements=["jurisdiction_id"])
    )


async def load_geography(
    session: AsyncSession, states: str, counties: str, places: str
) -> dict[str, int]:
    """Load all three files (already decoded text). Idempotent; commits once."""
    state_rows = parse_states(states)
    await upsert_jurisdictions(session, state_rows, parent_by_state=None)
    by_state = await state_ids(session)
    county_rows = parse_counties(counties)
    place_rows = parse_places(places)
    await upsert_jurisdictions(session, county_rows, by_state)
    await upsert_jurisdictions(session, place_rows, by_state)
    await ensure_coverage_rows(session)
    await session.commit()
    return {
        "states": len(state_rows),
        "counties": len(county_rows),
        "places": len(place_rows),
    }
