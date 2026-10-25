import asyncio

import pytest
from sqlalchemy import func, select

from app.discovery import zip_resolver
from app.discovery.models import IngestionJob, Program, UserLocation
from app.discovery.zip_resolver import normalize_zip, resolve_with_timeout, resolve_zip
from app.models import User


async def test_normalize_zip():
    assert normalize_zip("78701") == "78701"
    assert normalize_zip("78701-1234") == "78701"
    for bad in ("7870", "787011", "78701-12", "abcde"):
        with pytest.raises(ValueError):
            normalize_zip(bad)


async def test_single_county_zip_resolves_to_city(db_session, geo):
    r = await resolve_zip(db_session, "78701")
    assert (r.method, r.state_id, r.county_id, r.city_id) == (
        "zcta_place",
        geo.texas.id,
        geo.travis.id,
        geo.austin.id,
    )
    assert r.confidence == 1.0


async def test_multi_county_zip_picks_highest_res_ratio(db_session, geo):
    r = await resolve_zip(db_session, "63138")
    assert r.state_id == geo.missouri.id
    assert r.county_id == geo.st_louis_county.id
    assert [a["id"] for a in r.alternates if a["level"] == "county"] == [
        geo.st_louis_city_county.id
    ]
    # Its ZCTA only touches a CDP, so the county is the local jurisdiction.
    assert r.method == "county_only" and r.city_id is None


async def test_po_box_zip_falls_back_to_usps_city_name(db_session, geo):
    r = await resolve_zip(db_session, "78711")
    assert (r.method, r.city_id, r.confidence) == ("usps_city_name", geo.austin.id, 0.6)


async def test_cdp_zip_falls_back_to_county(db_session, geo):
    r = await resolve_zip(db_session, "78734")
    # Hudson Bend CDP has no city government; Austin's 5% share is under the 10% bar.
    assert (r.method, r.city_id, r.county_id) == ("county_only", None, geo.travis.id)


async def test_unknown_and_territory_zips_are_unresolved(db_session, geo):
    assert (await resolve_zip(db_session, "99999")).method == "unresolved"
    assert (await resolve_zip(db_session, "00601")).method == "unresolved"


async def test_lookup_timeout_yields_unresolved(db_session, geo, monkeypatch):
    async def slow(session, zip_input):
        await asyncio.sleep(1)

    monkeypatch.setattr(zip_resolver, "resolve_zip", slow)
    r = await resolve_with_timeout(db_session, "78701", timeout=0.05)
    assert r.method == "unresolved" and r.zip == "78701"


async def _signup(test_client, email: str, zip_code: str):
    return await test_client.post(
        "/auth/register",
        json={"email": email, "password": "Secret123!", "zip_code": zip_code},
    )


async def test_signup_78701_resolves_and_enqueues_state_and_city(
    test_client, db_session, geo
):
    response = await _signup(test_client, "new@example.com", "78701")
    assert response.status_code == 201
    user = await db_session.scalar(select(User).where(User.email == "new@example.com"))
    loc = await db_session.get(UserLocation, user.id)
    assert (loc.state_id, loc.county_id, loc.city_id) == (
        geo.texas.id,
        geo.travis.id,
        geo.austin.id,
    )
    jobs = (
        await db_session.execute(
            select(IngestionJob.jurisdiction_id, IngestionJob.priority)
        )
    ).all()
    assert sorted(jobs) == sorted([(geo.texas.id, 10), (geo.austin.id, 10)])


async def test_signup_with_unknown_zip_still_succeeds(test_client, db_session, geo):
    response = await _signup(test_client, "far@example.com", "99999")
    assert response.status_code == 201
    user = await db_session.scalar(select(User).where(User.email == "far@example.com"))
    loc = await db_session.get(UserLocation, user.id)
    assert loc.method == "unresolved"
    assert await db_session.scalar(select(func.count()).select_from(IngestionJob)) == 0


async def test_signup_rejects_bad_zip(test_client, geo):
    assert (await _signup(test_client, "bad@example.com", "7870")).status_code == 422


async def test_federal_programs_show_right_after_signup(test_client, db_session, geo):
    db_session.add_all(
        [
            Program(
                jurisdiction_id=geo.federal.id,
                name="SNAP",
                normalized_name="snap",
                audience="individual",
                review_status="published",
                origin="seed_sam_gov",
            ),
            Program(
                jurisdiction_id=geo.federal.id,
                name="Grants to States",
                normalized_name="grants to states",
                audience="government",
                review_status="published",
                origin="seed_sam_gov",
            ),
            Program(
                jurisdiction_id=geo.federal.id,
                name="Unvetted",
                normalized_name="unvetted",
                audience="individual",
                review_status="needs_review",
                origin="seed_sam_gov",
            ),
        ]
    )
    await db_session.commit()
    await _signup(test_client, "fed@example.com", "78701")
    login = await test_client.post(
        "/auth/jwt/login",
        data={"username": "fed@example.com", "password": "Secret123!"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    body = (await test_client.get("/programs/me", headers=headers)).json()
    assert [p["name"] for p in body["federal"]] == [
        "SNAP"
    ]  # hidden: non-individual, needs_review
    assert body["location"]["display_name"] == "Austin, TX"
    assert sorted(body["gathering"]) == ["Austin, TX", "Texas"]
