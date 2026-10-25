"""Federal programs from GSA's public Assistance Listings extract (spec Section 6).

The extract is a CC0 CSV on Data.gov: no account, no key, no rate limit.
It has no beneficiary type codes, so the audience comes from the beneficiary
eligibility text; anything uncertain is stored as needs_review (hidden).
"""

import csv
import io
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.geography import ensure_federal
from app.discovery.models import JurisdictionCoverage, Program
from app.discovery.normalize import normalize_name

log = logging.getLogger(__name__)

CSV_URL = (
    "https://s3.amazonaws.com/falextracts/Assistance%20Listings/datagov/"
    "AssistanceListings_DataGov_PUBLIC_CURRENT.csv"
)

# Federal programs people apply for through their state (Section 6). Always shown
# to individuals: their eligibility text talks about states, which fools the rules.
FEDERAL_STATE_PROGRAMS = {
    "SNAP": "10.551",
    "WIC": "10.557",
    "Medicaid": "93.778",
    "CHIP": "93.767",
    "TANF": "93.558",
    "LIHEAP": "93.568",
    "Unemployment Insurance": "17.225",
}

# Well-known programs for people that are funded as formula grants, which the
# assistance-type rule would otherwise hide.
ALWAYS_SHOW = {
    *FEDERAL_STATE_PROGRAMS.values(),
    "10.553",  # School Breakfast Program
    "10.555",  # National School Lunch Program
    "81.042",  # Weatherization Assistance for Low-Income Persons
    "10.417",  # Very Low-Income Housing Repair Loans and Grants
}

# Assistance types that reach people directly (grants and cooperative agreements
# go to agencies and organizations). Matched as substrings, singular or plural.
PEOPLE_ASSISTANCE_TYPES = (
    "DIRECT PAYMENT",
    "DIRECT LOAN",
    "GUARANTEED/INSURED LOAN",
    "INSURANCE",
    "PROVISION OF SPECIALIZED SERVICES",
    "ADVISORY SERVICES AND COUNSELING",
)

# related_federal_program aliases -> assistance listing id (Section 11).
FEDERAL_ALIASES = {
    "snap": "10.551",
    "food stamps": "10.551",
    "supplemental nutrition assistance program": "10.551",
    "wic": "10.557",
    "women infants and children": "10.557",
    "medicaid": "93.778",
    "chip": "93.767",
    "childrens health insurance program": "93.767",
    "children s health insurance program": "93.767",
    "tanf": "93.558",
    "temporary assistance for needy families": "93.558",
    "liheap": "93.568",
    "low income home energy assistance program": "93.568",
    "unemployment insurance": "17.225",
    "unemployment": "17.225",
}

_AUDIENCE_PATTERNS = {
    "individual": r"\b(individual|person|people|household|famil|low[- ]income|veteran|student|elderly|senior|older (adult|american)|disab|child|youth|infant|women|mother|unemployed|worker|homeless|tenant|renter|homeowner|citizen|resident|patient|survivor|victim|refugee|farmworker)",
    "government": r"\b(state|local government|county|counties|municipal|tribal|tribe|territor|government|agenc)",
    "organization": r"\b(nonprofit|non-profit|institution|universit|college|organization|hospital|school district)",
    "business": r"\b(small business|for-profit|business|firm|producer|exporter|lender)",
}


def classify_audience(
    beneficiary_text: str, assistance_types: str | None = None, title: str = ""
) -> tuple[str, bool]:
    """Beneficiary text (+ assistance types, title) -> (audience, confident).

    Individual needs people mentioned more often than any other audience and
    (when types are given) a type that reaches people directly. Anything else
    is a best guess stored for review, so the rule errs toward hiding.
    """
    if "business" in title.lower():
        return "business", False
    t = beneficiary_text.lower()
    if "general public" in t:  # e.g. cleanup programs that "protect the general public"
        return "government", False
    hits = {a: len(re.findall(p, t)) for a, p in _AUDIENCE_PATTERNS.items()}
    reaches_people = assistance_types is None or any(
        p in assistance_types.upper() for p in PEOPLE_ASSISTANCE_TYPES
    )
    if hits["individual"] > max(
        hits["government"], hits["organization"], hits["business"]
    ):
        return "individual", reaches_people
    best = max(hits, key=lambda a: hits[a])
    return (best if hits[best] else "organization"), False


_SMALL_WORDS = {"and", "of", "for", "the", "on", "in", "to", "a", "an"}


def agency_name(raw: str) -> str | None:
    """'FOOD AND NUTRITION SERVICE, AGRICULTURE, DEPARTMENT OF' -> 'Food and Nutrition Service'."""
    first = raw.split(",")[0].strip()
    if not first:
        return None
    words = first.lower().split()
    return " ".join(
        w if (i and w in _SMALL_WORDS) else w.capitalize() for i, w in enumerate(words)
    )


def decode_csv(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")  # GSA ships Windows-1252


def _clean(value: str | None) -> str | None:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value or None


def row_to_program(row: dict[str, str], federal_id: int) -> dict[str, Any]:
    listing_id = row["Program Number"].strip()
    title = _clean(row.get("Program Title")) or listing_id
    beneficiary = _clean(row.get("Beneficiary Eligibility (082)"))
    audience, confident = classify_audience(
        beneficiary or "", row.get("Types of Assistance (060)") or "", title
    )
    if listing_id in ALWAYS_SHOW:
        audience, confident = "individual", True
    website = _clean(row.get("Website Address (153)"))
    if website and not website.startswith(("http://", "https://")):
        website = f"https://{website}"
    return {
        "jurisdiction_id": federal_id,
        "name": title,
        "normalized_name": normalize_name(title),
        "administering_agency": agency_name(row.get("Federal Agency (030)") or ""),
        "audience": audience,
        "summary": _clean(row.get("Objectives (050)")),
        "eligibility_summary": beneficiary,
        "info_url": website or _clean(row.get("URL")),
        "external_ids": {"assistance_listing_id": listing_id},
        "status": "active",  # the PUBLIC_CURRENT extract only has current listings
        "review_status": "published" if confident else "needs_review",
        "confidence": 1.0 if confident else 0.5,
        # The spec's origin vocabulary: these are the SAM.gov catalog's listings.
        "origin": "seed_sam_gov",
    }


def parse_csv(data: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(data))
    return [r for r in reader if (r.get("Program Number") or "").strip()]


async def upsert_rows(
    session: AsyncSession, rows: list[dict[str, str]], federal_id: int
) -> int:
    programs = [row_to_program(r, federal_id) for r in rows]
    # Distinct listings can share a title; keep (jurisdiction, normalized_name) unique
    # by suffixing the listing id, so neither listing is silently dropped.
    owner: dict[str, str] = {
        name: lid
        for name, lid in (
            await session.execute(
                select(
                    Program.normalized_name,
                    Program.external_ids["assistance_listing_id"].astext,
                ).where(Program.jurisdiction_id == federal_id)
            )
        ).all()
    }
    for p in programs:
        lid = p["external_ids"]["assistance_listing_id"]
        if owner.get(p["normalized_name"], lid) != lid:
            p["normalized_name"] = f"{p['normalized_name']} {normalize_name(lid)}"
        owner[p["normalized_name"]] = lid

    for p in programs:
        stmt = insert(Program).values(**p)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    "jurisdiction_id",
                    text("(external_ids->>'assistance_listing_id')"),
                ],
                index_where=text("external_ids->>'assistance_listing_id' IS NOT NULL"),
                set_={
                    c: stmt.excluded[c]
                    for c in (
                        "name",
                        "normalized_name",
                        "administering_agency",
                        "audience",
                        "summary",
                        "eligibility_summary",
                        "info_url",
                        "status",
                        "review_status",
                        "confidence",
                    )
                }
                | {"last_verified_at": text("now()"), "updated_at": text("now()")},
            )
        )
    return len(programs)


async def import_federal(session: AsyncSession, csv_text: str) -> dict[str, Any]:
    """Upsert every listing in the extract. Idempotent; listings that dropped out
    of the current extract are marked inactive."""
    federal_id = await ensure_federal(session)
    rows = parse_csv(csv_text)
    imported = await upsert_rows(session, rows, federal_id)
    current = [r["Program Number"].strip() for r in rows]
    await session.execute(
        update(Program)
        .where(
            Program.jurisdiction_id == federal_id,
            Program.origin == "seed_sam_gov",
            Program.external_ids["assistance_listing_id"].astext.not_in(current),
        )
        .values(status="inactive")
    )

    published = await session.scalar(
        select(func.count())
        .select_from(Program)
        .where(
            Program.jurisdiction_id == federal_id,
            Program.review_status == "published",
            Program.status == "active",
            Program.audience == "individual",
        )
    )
    await session.execute(
        insert(JurisdictionCoverage)
        .values(jurisdiction_id=federal_id, status="covered")
        .on_conflict_do_nothing(index_elements=["jurisdiction_id"])
    )
    await session.execute(
        update(JurisdictionCoverage)
        .where(JurisdictionCoverage.jurisdiction_id == federal_id)
        .values(
            status="covered",
            published_program_count=published or 0,
            last_discovered_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    missing = {n: i for n, i in FEDERAL_STATE_PROGRAMS.items() if i not in set(current)}
    if missing:
        log.warning(
            "Federal-state parents missing from the extract, dropped: %s", missing
        )
    return {
        "imported": imported,
        "shown_to_individuals": published,
        "missing_parents": missing,
    }


async def federal_parent_ids(session: AsyncSession) -> dict[str, int]:
    """assistance listing id -> program id, for the federal-state parents that exist."""
    rows = (
        await session.execute(
            select(
                Program.external_ids["assistance_listing_id"].astext, Program.id
            ).where(
                Program.external_ids["assistance_listing_id"].astext.in_(
                    list(FEDERAL_STATE_PROGRAMS.values())
                )
            )
        )
    ).all()
    return {lid: pid for lid, pid in rows}
