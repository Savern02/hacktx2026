"""Offline fixtures for the discovery pipeline. No test here makes a live call."""

from dataclasses import dataclass

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.discovery.geography import load_geography
from app.discovery.models import Jurisdiction, ZctaPlace, ZipCounty
from app.discovery.serpapi_client import reset_global_pause

STATES = "USPS\tGEOID\tNAME\tALAND\nTX\t48\tTexas\t1\nMO\t29\tMissouri\t1\nPR\t72\tPuerto Rico\t1\n"
COUNTIES = (
    "USPS\tGEOID\tANSICODE\tNAME\tALAND\n"
    "TX\t48453\t1\tTravis County\t1\n"
    "MO\t29189\t1\tSt. Louis County\t1\n"
    "MO\t29510\t1\tSt. Louis city\t1\n"
)
PLACES = (
    "STATE|STATEFP|PLACEFP|PLACENS|PLACENAME|TYPE|CLASSFP|FUNCSTAT|COUNTIES\n"
    "TX|48|05000|1|Austin city|INCORPORATED PLACE|C1|A|Travis County\n"
    "TX|48|35000|1|Hudson Bend CDP|CENSUS DESIGNATED PLACE|U1|S|Travis County\n"
    "MO|29|65000|1|St. Louis city|INCORPORATED PLACE|C7|A|St. Louis city\n"
    "MO|29|69266|1|Spanish Lake CDP|CENSUS DESIGNATED PLACE|U1|S|St. Louis County\n"
)


def zc(zip_code: str, county: str, res: float, city: str | None, state: str) -> dict:
    return {
        "zip": zip_code,
        "county_geoid": county,
        "usps_city": city,
        "usps_state": state,
        "res_ratio": res,
        "tot_ratio": res,
        "data_year": 2023,
        "data_quarter": 1,
    }


ZIP_COUNTY = [
    zc("78701", "48453", 1.0, "AUSTIN", "TX"),  # single county, inside Austin
    # Shaped like HUD 2023 Q1 for 63138: split between St. Louis County and St. Louis city.
    zc("63138", "29189", 0.998, "SAINT LOUIS", "MO"),
    zc("63138", "29510", 0.002, "SAINT LOUIS", "MO"),
    zc("78711", "48453", 1.0, "AUSTIN", "TX"),  # PO-box-only: no ZCTA
    zc("78734", "48453", 1.0, "AUSTIN", "TX"),  # mostly Hudson Bend CDP
    zc("00601", "72001", 1.0, "ADJUNTAS", "PR"),  # territory: out of v1 scope
]
ZCTA_PLACE = [
    {
        "zcta": "78701",
        "place_geoid": "4805000",
        "land_part_m2": 3906395,
        "zcta_land_m2": 3906395,
    },
    {
        "zcta": "78734",
        "place_geoid": "4835000",
        "land_part_m2": 60,
        "zcta_land_m2": 100,
    },
    {"zcta": "78734", "place_geoid": "4805000", "land_part_m2": 5, "zcta_land_m2": 100},
    {
        "zcta": "63138",
        "place_geoid": "2969266",
        "land_part_m2": 70,
        "zcta_land_m2": 100,
    },
]


@dataclass
class Geo:
    federal: Jurisdiction
    texas: Jurisdiction
    missouri: Jurisdiction
    travis: Jurisdiction
    st_louis_county: Jurisdiction
    st_louis_city_county: Jurisdiction
    austin: Jurisdiction
    hudson_bend: Jurisdiction


async def _get(session: AsyncSession, level: str, geoid: str | None) -> Jurisdiction:
    stmt = select(Jurisdiction).where(Jurisdiction.level == level)
    if geoid:
        stmt = stmt.where(Jurisdiction.geoid == geoid)
    j = await session.scalar(stmt)
    assert j is not None
    return j


@pytest_asyncio.fixture
async def geo(db_session: AsyncSession) -> Geo:
    await load_geography(db_session, STATES, COUNTIES, PLACES)
    db_session.add_all(
        [ZipCounty(**r) for r in ZIP_COUNTY] + [ZctaPlace(**r) for r in ZCTA_PLACE]
    )
    await db_session.commit()
    return Geo(
        federal=await _get(db_session, "federal", None),
        texas=await _get(db_session, "state", "48"),
        missouri=await _get(db_session, "state", "29"),
        travis=await _get(db_session, "county", "48453"),
        st_louis_county=await _get(db_session, "county", "29189"),
        st_louis_city_county=await _get(db_session, "county", "29510"),
        austin=await _get(db_session, "city", "4805000"),
        hudson_bend=await _get(db_session, "city", "4835000"),
    )


@pytest_asyncio.fixture
async def sessions(engine) -> async_sessionmaker[AsyncSession]:
    """Independent sessions on the test DB, for concurrency tests."""
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _no_serpapi_pause():
    reset_global_pause()
    yield
    reset_global_pause()
