"""ZIP -> state / county / city, from local tables only (spec Section 7)."""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Jurisdiction, ZctaPlace, ZipCounty
from app.discovery.normalize import normalize_city

ZIP_RE = re.compile(r"^(\d{5})(?:-\d{4})?$")
MIN_PLACE_SHARE = 0.10
USPS_NAME_CONFIDENCE = 0.6
RESOLVE_TIMEOUT_S = 0.2


def normalize_zip(value: str) -> str:
    """Accept 12345 or 12345-6789 and keep the first five digits."""
    match = ZIP_RE.match(value.strip())
    if not match:
        raise ValueError("ZIP code must look like 12345 or 12345-6789")
    return match.group(1)


@dataclass
class Resolution:
    zip: str
    method: str  # zcta_place | usps_city_name | county_only | unresolved
    confidence: float
    state_id: int | None = None
    county_id: int | None = None
    city_id: int | None = None
    alternates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def local_id(self) -> int | None:
        """The user's local jurisdiction: the city, or the county when there is none."""
        return self.city_id or self.county_id


def unresolved(zip_code: str) -> Resolution:
    return Resolution(zip=zip_code, method="unresolved", confidence=0)


async def resolve_zip(session: AsyncSession, zip_input: str) -> Resolution:
    zip_code = normalize_zip(zip_input)

    county_rows = (
        (
            await session.execute(
                select(ZipCounty)
                .where(ZipCounty.zip == zip_code)
                .order_by(ZipCounty.res_ratio.desc(), ZipCounty.tot_ratio.desc())
            )
        )
        .scalars()
        .all()
    )
    if not county_rows:
        return unresolved(zip_code)

    best = county_rows[0]
    state = await session.scalar(
        select(Jurisdiction).where(
            Jurisdiction.level == "state", Jurisdiction.geoid == best.county_geoid[:2]
        )
    )
    if state is None:  # territory, or a state outside v1 scope
        return unresolved(zip_code)

    counties = {
        j.geoid: j
        for j in (
            await session.execute(
                select(Jurisdiction).where(
                    Jurisdiction.level == "county",
                    Jurisdiction.geoid.in_([r.county_geoid for r in county_rows]),
                )
            )
        ).scalars()
    }
    county = counties.get(best.county_geoid)
    alternates: list[dict[str, Any]] = [
        {
            "level": "county",
            "id": counties[r.county_geoid].id,
            "name": counties[r.county_geoid].display_name,
            "res_ratio": float(r.res_ratio),
        }
        for r in county_rows[1:]
        if r.county_geoid in counties
    ]
    result = Resolution(
        zip=zip_code,
        method="county_only",
        confidence=round(float(min(best.res_ratio, 1)), 2),
        state_id=state.id,
        county_id=county.id if county else None,
        alternates=alternates,
    )

    # City via ZCTA overlap: the ZIP is treated as its ZCTA.
    overlaps = (
        await session.execute(
            select(ZctaPlace, Jurisdiction)
            .join(
                Jurisdiction,
                (Jurisdiction.geoid == ZctaPlace.place_geoid)
                & (Jurisdiction.level == "city"),
            )
            .where(ZctaPlace.zcta == zip_code)
        )
    ).all()
    candidates = sorted(
        (
            (zp.land_part_m2 / zp.zcta_land_m2 if zp.zcta_land_m2 else 0.0, place)
            for zp, place in overlaps
            if place.is_incorporated and place.parent_id == state.id
        ),
        key=lambda c: c[0],
        reverse=True,
    )
    qualifying = [
        (share, place) for share, place in candidates if share >= MIN_PLACE_SHARE
    ]
    if qualifying:
        share, city = qualifying[0]
        result.method = "zcta_place"
        result.city_id = city.id
        result.confidence = round(min(share, 1.0), 2)
        result.alternates += [
            {"level": "city", "id": p.id, "name": p.display_name, "share": round(s, 2)}
            for s, p in qualifying[1:]
        ]
        return result

    if overlaps:
        # The ZIP has a ZCTA but it only touches CDPs or slivers of cities:
        # unincorporated area, so the county is the local jurisdiction.
        return result

    # No ZCTA at all (PO-box-only ZIPs, for example): match the USPS city name.
    if best.usps_city:
        wanted = normalize_city(best.usps_city)
        places = (
            await session.execute(
                select(Jurisdiction).where(
                    Jurisdiction.level == "city",
                    Jurisdiction.parent_id == state.id,
                    Jurisdiction.is_incorporated.is_(True),
                )
            )
        ).scalars()
        for place in places:
            if normalize_city(place.name) == wanted:
                result.method = "usps_city_name"
                result.city_id = place.id
                result.confidence = USPS_NAME_CONFIDENCE
                break
    return result


async def resolve_with_timeout(
    session: AsyncSession, zip_input: str, timeout: float = RESOLVE_TIMEOUT_S
) -> Resolution:
    """Never raises: a slow or failing lookup yields 'unresolved' (retried by the worker)."""
    try:
        return await asyncio.wait_for(resolve_zip(session, zip_input), timeout)
    except ValueError:
        raise
    except Exception:
        return unresolved(normalize_zip(zip_input))
