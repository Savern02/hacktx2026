"""Programs for the signed-in user's area (spec Sections 2.10, 7.7 and 8)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.discovery.coverage import check_and_enqueue
from app.discovery.federal_programs import FEDERAL_STATE_PROGRAMS
from app.discovery.models import (
    Jurisdiction,
    JurisdictionCoverage,
    Program,
    UserLocation,
)
from app.models import User
from app.schemas import (
    LocationRead,
    LocationUpdate,
    PlaceRef,
    ProgramRead,
    ProgramsForUser,
)
from app.users import current_active_user

router = APIRouter(tags=["programs"])

VISIBLE = (
    Program.review_status == "published",
    Program.status == "active",
    Program.audience == "individual",
)


def _program(p: Program, j: Jurisdiction) -> ProgramRead:
    return ProgramRead(
        id=p.id,
        name=p.name,
        jurisdiction=j.display_name,
        level=j.level,
        administering_agency=p.administering_agency,
        categories=list(p.categories or []),
        summary=p.summary,
        eligibility_summary=p.eligibility_summary,
        how_to_apply=p.how_to_apply,
        apply_url=p.apply_url,
        info_url=p.info_url,
        phone=p.phone,
    )


async def _location(session: AsyncSession, loc: UserLocation) -> LocationRead:
    ids = [i for i in (loc.state_id, loc.county_id, loc.city_id) if i]
    alt_ids = [
        a["id"] for a in loc.alternates or [] if isinstance(a, dict) and a.get("id")
    ]
    places = {
        j.id: j
        for j in (
            await session.execute(
                select(Jurisdiction).where(Jurisdiction.id.in_(ids + alt_ids))
            )
        ).scalars()
    }

    def ref(jid: int | None) -> PlaceRef | None:
        j = places.get(jid) if jid else None
        return PlaceRef(id=j.id, level=j.level, name=j.display_name) if j else None

    local = ref(loc.city_id) or ref(loc.county_id)
    return LocationRead(
        zip=loc.zip,
        method=loc.method,
        display_name=local.name if local else None,
        state=ref(loc.state_id),
        county=ref(loc.county_id),
        city=ref(loc.city_id),
        user_confirmed=loc.user_confirmed,
        alternates=[r for r in (ref(i) for i in alt_ids) if r],
    )


@router.get("/me", response_model=ProgramsForUser)
async def get_my_programs(
    q: str | None = Query(default=None, max_length=100),
    federal_limit: int = Query(default=20, ge=1, le=100),
    federal_offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    loc = await session.get(UserLocation, user.id)
    federal = await session.scalar(
        select(Jurisdiction).where(Jurisdiction.level == "federal")
    )
    local_ids = [
        i for i in ((loc.state_id, loc.county_id, loc.city_id) if loc else ()) if i
    ]

    def search(stmt):  # type: ignore[no-untyped-def]
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(Program.name.ilike(pattern), Program.summary.ilike(pattern))
            )
        return stmt

    local = []
    if local_ids:
        rows = await session.execute(
            search(
                select(Program, Jurisdiction)
                .join(Jurisdiction, Jurisdiction.id == Program.jurisdiction_id)
                .where(Program.jurisdiction_id.in_(local_ids), *VISIBLE)
                .order_by(
                    Jurisdiction.level.desc(), Program.name
                )  # city/county before state
            )
        )
        local = [_program(p, j) for p, j in rows.all()]

    federal_programs: list[ProgramRead] = []
    federal_total = 0
    if federal is not None:
        base = search(
            select(Program).where(Program.jurisdiction_id == federal.id, *VISIBLE)
        )
        federal_total = int(
            await session.scalar(select(func.count()).select_from(base.subquery())) or 0
        )
        # Programs people apply for near them (SNAP, Medicaid...) first; for a
        # search, title matches before summary-only matches.
        listing_id = Program.external_ids["assistance_listing_id"].astext
        order = [
            case((listing_id.in_(list(FEDERAL_STATE_PROGRAMS.values())), 0), else_=1)
        ]
        if q:
            order.insert(0, case((Program.name.ilike(f"%{q}%"), 0), else_=1))
        rows = await session.execute(
            base.order_by(*order, Program.name)
            .limit(federal_limit)
            .offset(federal_offset)
        )
        federal_programs = [_program(p, federal) for p in rows.scalars()]

    gathering: list[str] = []
    if local_ids:
        gathering = list(
            (
                await session.execute(
                    select(Jurisdiction.display_name)
                    .join(
                        JurisdictionCoverage,
                        JurisdictionCoverage.jurisdiction_id == Jurisdiction.id,
                    )
                    .where(
                        Jurisdiction.id.in_(local_ids),
                        JurisdictionCoverage.status.in_(["queued", "in_progress"]),
                    )
                )
            ).scalars()
        )

    return ProgramsForUser(
        location=await _location(session, loc) if loc else None,
        gathering=gathering,
        local=local,
        federal=federal_programs,
        federal_total=federal_total,
    )


@router.put("/me/location", response_model=LocationRead)
async def change_my_location(
    body: LocationUpdate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """'Not right? Change city.' Pick one of the alternates; it's never auto-overwritten."""
    loc = await session.get(UserLocation, user.id, with_for_update=True)
    if loc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NO_LOCATION")
    choice = next(
        (
            a
            for a in loc.alternates or []
            if isinstance(a, dict) and a.get("id") == body.jurisdiction_id
        ),
        None,
    )
    if choice is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="NOT_AN_ALTERNATE"
        )
    target = await session.get(Jurisdiction, body.jurisdiction_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="NOT_AN_ALTERNATE"
        )

    previous = {loc.state_id, loc.county_id, loc.city_id}
    old = (
        {"level": "city", "id": loc.city_id}
        if loc.city_id
        else {"level": "county", "id": loc.county_id}
    )
    if target.level == "city":
        loc.city_id = target.id
    else:
        loc.county_id, loc.city_id = target.id, None
    # The old pick becomes an alternate so the user can switch back.
    loc.alternates = [a for a in loc.alternates if a.get("id") != target.id] + (
        [old] if old["id"] else []
    )
    loc.user_confirmed = True
    if target.id not in previous:
        await check_and_enqueue(session, target.id, count_user=True)
    await session.commit()
    await session.refresh(loc)
    return await _location(session, loc)
