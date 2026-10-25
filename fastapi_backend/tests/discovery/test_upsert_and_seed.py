import pytest
from sqlalchemy import func, select

from app.discovery.models import (
    JurisdictionCoverage,
    Program,
    ProgramSource,
    SourceDocument,
)
from app.discovery.federal_programs import (
    agency_name,
    classify_audience,
    decode_csv,
    import_federal,
)
from app.discovery.upsert import upsert_program
from app.discovery.validator import Candidate, Evidence, ValidCandidate


def valid(
    name: str, jurisdiction_id: int, confidence: float = 0.9, **kw
) -> ValidCandidate:
    c = Candidate(
        name=name,
        jurisdiction_level="city",
        jurisdiction_name="Austin",
        audience="individual",
        categories=["utilities"],
        summary="Utility discounts.",
        is_active="yes",
        evidence=Evidence(name=name),
        confidence=confidence,
        **kw,
    )
    return ValidCandidate(
        candidate=c,
        jurisdiction_id=jurisdiction_id,
        status="active",
        force_review=False,
    )


async def source(session, url: str, tier: int) -> SourceDocument:
    doc = SourceDocument(canonical_url=url, domain="austintexas.gov", trust_tier=tier)
    session.add(doc)
    await session.flush()
    return doc


async def test_same_program_from_two_pages_is_one_row_two_sources(db_session, geo):
    a = await source(db_session, "https://www.austintexas.gov/cap", 1)
    b = await source(db_session, "https://www.austintexas.gov/utilities/help", 1)
    assert (
        await upsert_program(
            db_session,
            valid("Customer Assistance Program", geo.austin.id),
            a,
            auto_publish_confidence=0.8,
            federal_parents={},
        )
        == "inserted"
    )
    assert (
        await upsert_program(
            db_session,
            valid("Customer Assistance Program", geo.austin.id),
            b,
            auto_publish_confidence=0.8,
            federal_parents={},
        )
        == "updated"
    )
    assert await db_session.scalar(select(func.count()).select_from(Program)) == 1
    assert await db_session.scalar(select(func.count()).select_from(ProgramSource)) == 2


async def test_similar_names_merge_but_different_names_do_not(db_session, geo):
    doc = await source(db_session, "https://www.austintexas.gov/cap", 1)
    await upsert_program(
        db_session,
        valid("Customer Assistance Program", geo.austin.id),
        doc,
        auto_publish_confidence=0.8,
        federal_parents={},
    )
    # similarity("customer assistance program", "customer assistance programs") ~ 0.9
    assert (
        await upsert_program(
            db_session,
            valid("Customer Assistance Programs", geo.austin.id),
            doc,
            auto_publish_confidence=0.8,
            federal_parents={},
        )
        == "updated"
    )
    assert (
        await upsert_program(
            db_session,
            valid("Emergency Rental Assistance", geo.austin.id),
            doc,
            auto_publish_confidence=0.8,
            federal_parents={},
        )
        == "inserted"
    )
    assert await db_session.scalar(select(func.count()).select_from(Program)) == 2


async def test_publish_rules(db_session, geo):
    tier1 = await source(db_session, "https://www.austintexas.gov/a", 1)
    tier3 = await source(db_session, "https://www.211texas.org/a", 3)
    await upsert_program(
        db_session,
        valid("Program A", geo.austin.id, 0.95),
        tier1,
        auto_publish_confidence=0.8,
        federal_parents={},
    )
    await upsert_program(
        db_session,
        valid("Program B", geo.austin.id, 0.5),
        tier1,
        auto_publish_confidence=0.8,
        federal_parents={},
    )
    await upsert_program(
        db_session,
        valid("Program C", geo.austin.id, 0.99),
        tier3,
        auto_publish_confidence=0.8,
        federal_parents={},
    )
    rows = dict(
        (await db_session.execute(select(Program.name, Program.review_status))).all()
    )
    assert rows == {
        "Program A": "published",
        "Program B": "needs_review",
        "Program C": "needs_review",
    }


async def test_state_version_links_to_federal_parent(db_session, geo):
    snap = Program(
        jurisdiction_id=geo.federal.id,
        name="SNAP",
        normalized_name="snap",
        audience="individual",
        origin="seed_sam_gov",
        external_ids={"assistance_listing_id": "10.551"},
    )
    db_session.add(snap)
    await db_session.flush()
    doc = await source(db_session, "https://www.hhs.texas.gov/snap", 2)
    await upsert_program(
        db_session,
        valid("Texas SNAP", geo.texas.id, related_federal_program="Food Stamps"),
        doc,
        auto_publish_confidence=0.8,
        federal_parents={"10.551": snap.id},
    )
    texas_snap = await db_session.scalar(
        select(Program).where(Program.name == "Texas SNAP")
    )
    assert texas_snap.parent_program_id == snap.id


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Low-income households and individuals.", ("individual", True)),
        ("Veterans and their surviving spouses.", ("individual", True)),
        ("Students and their families.", ("individual", True)),
        ("State and local governments.", ("government", False)),
        ("Nonprofit organizations and universities.", ("organization", False)),
        ("Small businesses and for-profit firms.", ("business", False)),
        ("", ("organization", False)),
        # Ties go to individuals: the program still reaches people.
        # Ties aren't confident: stored for review, hidden from users.
        ("States distribute benefits to eligible households.", ("individual", False)),
        ("The general public benefits from cleaner land.", ("government", False)),
    ],
)
def test_audience_from_beneficiary_text(text, expected):
    assert classify_audience(text) == expected


def test_audience_needs_assistance_that_reaches_people():
    people = "Low-income households and individuals."
    assert classify_audience(people, "DIRECT PAYMENT FOR SPECIFIED USE") == (
        "individual",
        True,
    )
    assert classify_audience(people, "PROJECT GRANTS") == ("individual", False)
    assert classify_audience(people, "DIRECT LOANS", "8(a) Business Development") == (
        "business",
        False,
    )


def test_agency_name_and_cp1252_decoding():
    assert (
        agency_name("FOOD AND NUTRITION SERVICE, AGRICULTURE, DEPARTMENT OF")
        == "Food and Nutrition Service"
    )
    assert (
        decode_csv("Public Law 88\u2013525".encode("cp1252"))
        == "Public Law 88\u2013525"
    )


HEADER = '"Program Title","Program Number","Federal Agency (030)","Objectives (050)","Beneficiary Eligibility (082)","Website Address (153)","URL"'


def extract(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


SNAP = '"Supplemental Nutrition Assistance Program","10.551","FOOD AND NUTRITION SERVICE, AGRICULTURE, DEPARTMENT OF","Improve nutrition.","Low-income households.","www.fns.usda.gov/snap",""'
# Mentions states more than households, but it's a federal-state program: always shown.
LIHEAP = '"Low-Income Home Energy Assistance","93.568","ADMINISTRATION FOR CHILDREN AND FAMILIES","Help with energy bills.","States, territories and tribal governments serve low-income households.","",""'
ROADS = '"Highway Planning and Construction","20.205","FEDERAL HIGHWAY ADMINISTRATION","Build roads.","State and local governments.","",""'
# Same title as SNAP but a different listing: both must be kept.
TWIN = '"Supplemental Nutrition Assistance Program","10.999","FOOD AND NUTRITION SERVICE","Other.","Households.","",""'


async def test_federal_import_is_idempotent(db_session, geo):
    data = extract(SNAP, LIHEAP, ROADS, TWIN)
    first = await import_federal(db_session, data)
    await import_federal(db_session, data)
    assert first["imported"] == 4
    assert await db_session.scalar(select(func.count()).select_from(Program)) == 4

    by_id = {
        p.external_ids["assistance_listing_id"]: p
        for p in (await db_session.execute(select(Program))).scalars()
    }
    snap = by_id["10.551"]
    assert (
        snap.audience,
        snap.review_status,
        snap.administering_agency,
        snap.info_url,
    ) == (
        "individual",
        "published",
        "Food and Nutrition Service",
        "https://www.fns.usda.gov/snap",
    )
    assert (by_id["93.568"].audience, by_id["93.568"].review_status) == (
        "individual",
        "published",
    )
    assert (by_id["20.205"].audience, by_id["20.205"].review_status) == (
        "government",
        "needs_review",
    )
    assert by_id["10.999"].normalized_name != snap.normalized_name
    coverage = await db_session.get(
        JurisdictionCoverage, geo.federal.id, populate_existing=True
    )
    # SNAP and LIHEAP (always shown); the twin has no assistance types, so it's held for review.
    assert (coverage.status, coverage.published_program_count) == ("covered", 2)


async def test_listings_dropped_from_the_extract_become_inactive(db_session, geo):
    await import_federal(db_session, extract(SNAP, ROADS))
    await import_federal(db_session, extract(SNAP))
    roads = await db_session.scalar(
        select(Program).where(Program.name == "Highway Planning and Construction")
    )
    assert roads.status == "inactive"
