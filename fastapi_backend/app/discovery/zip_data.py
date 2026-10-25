"""ZIP reference data loaders (spec Section 7).

- zcta_place: Census 2020 ZCTA5-to-Place relationship file (no key).
- zip_county: HUD-USPS ZIP crosswalk API, type=2, query=All (needs HUD_API_TOKEN).

Both loads replace the table inside one transaction (delete + insert), so readers
see either the old data or the new data, never a partial load.
"""

import csv
import io
from typing import Any

import httpx
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import ZctaPlace, ZipCounty

ZCTA_PLACE_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_place20_natl.txt"
)
HUD_URL = "https://www.huduser.gov/hudapi/public/usps"


def _detect_delimiter(header: str) -> str:
    return max(("|", "\t", ","), key=header.count)


def parse_zcta_place(data: str) -> list[dict[str, Any]]:
    data = data.lstrip("﻿")
    header = data.split("\n", 1)[0]
    reader = csv.DictReader(io.StringIO(data), delimiter=_detect_delimiter(header))
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for r in reader:
        zcta = (r.get("GEOID_ZCTA5_20") or "").strip()
        place = (r.get("GEOID_PLACE_20") or "").strip()
        # Skip ZCTA area outside any place, and place area outside any ZCTA.
        if not zcta or not place:
            continue
        key = (zcta, place)
        part = int(r["AREALAND_PART"] or 0)
        if key in merged:
            merged[key]["land_part_m2"] += part
        else:
            merged[key] = {
                "zcta": zcta,
                "place_geoid": place,
                "land_part_m2": part,
                "zcta_land_m2": int(r["AREALAND_ZCTA5_20"] or 0),
            }
    return list(merged.values())


def parse_hud_zip_county(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a HUD crosswalk response (type=2) to zip_county rows."""
    data = payload.get("data", payload)
    if isinstance(data, list):  # some HUD responses wrap the object in a list
        data = data[0]
    year = int(data["year"])
    quarter = int(data["quarter"])
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for r in data["results"]:
        zip_code = str(r["zip"]).zfill(5)
        county = str(r["geoid"]).zfill(5)
        rows[(zip_code, county)] = {
            "zip": zip_code,
            "county_geoid": county,
            # verify: HUD has named this field both "city" and "usps_zip_pref_city".
            "usps_city": r.get("city") or r.get("usps_zip_pref_city"),
            "usps_state": r.get("state") or r.get("usps_zip_pref_state"),
            "res_ratio": r["res_ratio"],
            "tot_ratio": r["tot_ratio"],
            "data_year": year,
            "data_quarter": quarter,
        }
    return list(rows.values())


ZCTA_COUNTY_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_county20_natl.txt"
)
CENSUS_DATA_QUARTER = 0  # marks rows that came from the Census fallback, not HUD


def parse_census_zcta_county(data: str) -> list[dict[str, Any]]:
    """Fallback zip_county rows from the Census 2020 ZCTA-county file (no key needed).

    Ratios are land-area shares, not HUD's residential ratios, and there is no USPS
    city name, so PO-box ZIPs can't use the name fallback. Prefer HUD when a token exists.
    """
    data = data.lstrip("\ufeff")
    header = data.split("\n", 1)[0]
    reader = csv.DictReader(io.StringIO(data), delimiter=_detect_delimiter(header))
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for r in reader:
        zcta = (r.get("GEOID_ZCTA5_20") or "").strip()
        county = (r.get("GEOID_COUNTY_20") or "").strip()
        zcta_land = int(r.get("AREALAND_ZCTA5_20") or 0)
        if not zcta or not county or not zcta_land:
            continue
        ratio = round(int(r["AREALAND_PART"] or 0) / zcta_land, 6)
        rows[(zcta, county)] = {
            "zip": zcta,
            "county_geoid": county,
            "usps_city": None,
            "usps_state": None,
            "res_ratio": ratio,
            "tot_ratio": ratio,
            "data_year": 2020,
            "data_quarter": CENSUS_DATA_QUARTER,
        }
    return list(rows.values())


async def fetch_hud_zip_county(token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.get(
            HUD_URL,
            params={"type": 2, "query": "All"},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()


async def _replace(
    session: AsyncSession, model: type, rows: list[dict[str, Any]]
) -> None:
    await session.execute(delete(model))
    # Postgres allows 32,767 bind parameters per statement.
    batch = 30000 // max(len(rows[0]), 1) if rows else 1
    for start in range(0, len(rows), batch):
        await session.execute(insert(model).values(rows[start : start + batch]))
    await session.commit()


async def load_zcta_place(session: AsyncSession, data: str) -> int:
    rows = parse_zcta_place(data)
    await _replace(session, ZctaPlace, rows)
    return len(rows)


async def load_zip_county(session: AsyncSession, payload: dict[str, Any]) -> int:
    rows = parse_hud_zip_county(payload)
    await _replace(session, ZipCounty, rows)
    return len(rows)


async def load_zip_county_census(session: AsyncSession, data: str) -> int:
    rows = parse_census_zcta_county(data)
    await _replace(session, ZipCounty, rows)
    return len(rows)
