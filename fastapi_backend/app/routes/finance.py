"""Money check-up (50/30/20, 28/36) from Nessie, and Equa's program matches."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.discovery.models import Jurisdiction, Program
from app.finance import service
from app.finance.models import ProgramApplication
from app.models import User
from app.routes.programs import _program
from app.schemas import (
    ApplicationStatusRead,
    ApplicationStatusUpdate,
    FinancialHealth,
    ProgramMatch,
    ProgramMatches,
)
from app.services.nessie_service import NessieError
from app.users import current_active_user

router = APIRouter(tags=["finance"])


def application_url(program: Program) -> str | None:
    """The apply link if it's a real absolute web URL, else the program's website."""
    for url in (program.apply_url, program.info_url):
        if not url:
            continue
        parts = urlsplit(url.strip())
        if (
            parts.scheme in ("http", "https")
            and parts.hostname
            and "." in parts.hostname
        ):
            return url.strip()
    return None


@router.get("/me/health", response_model=FinancialHealth)
async def get_my_financial_health(
    refresh: bool = Query(default=False),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    try:
        return await service.get_health(session, user, refresh=refresh)
    except service.NotConnected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="BANK_NOT_CONNECTED"
        )
    except NessieError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="BANK_UNAVAILABLE"
        )


@router.get("/me/program-matches", response_model=ProgramMatches)
async def get_my_program_matches(
    refresh: bool = Query(default=False),
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    try:
        result = await service.get_recommendations(session, user, refresh=refresh)
    except service.NotConnected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="BANK_NOT_CONNECTED"
        )
    except NessieError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="BANK_UNAVAILABLE"
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="ADVISOR_UNAVAILABLE"
        )

    ids = [r["program_id"] for r in result["recommendations"]]
    rows = await session.execute(
        select(Program, Jurisdiction)
        .join(Jurisdiction, Jurisdiction.id == Program.jurisdiction_id)
        .where(Program.id.in_(ids))
    )
    by_id = {p.id: (p, j) for p, j in rows.tuples()}
    status_rows = await session.execute(
        select(ProgramApplication.program_id, ProgramApplication.status).where(
            ProgramApplication.user_id == user.id,
            ProgramApplication.program_id.in_(ids),
        )
    )
    # Not dict(result): SQLAlchemy results have .keys(), so dict() treats them as mappings.
    statuses = {pid: st for pid, st in status_rows.tuples()}
    return ProgramMatches(
        summary=result["summary"],
        matches=[
            ProgramMatch(
                program=_program(*by_id[r["program_id"]]),
                reason=r["reason"],
                confidence=r["confidence"],
                application_url=application_url(by_id[r["program_id"]][0]),
                application_status=statuses.get(r["program_id"], "in-progress"),
            )
            for r in result["recommendations"]
            if r["program_id"] in by_id
        ],
        computed_at=result["computed_at"],
    )


@router.put("/me/applications/{program_id}", response_model=ApplicationStatusRead)
async def set_my_application_status(
    program_id: int,
    body: ApplicationStatusUpdate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Mark a matched program's application as in progress or complete."""
    visible = await session.scalar(
        select(Program.id).where(
            Program.id == program_id,
            Program.review_status == "published",
            Program.status == "active",
            Program.audience == "individual",
        )
    )
    if visible is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="PROGRAM_NOT_FOUND"
        )
    stmt = insert(ProgramApplication).values(
        user_id=user.id, program_id=program_id, status=body.status
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "program_id"],
            set_={"status": stmt.excluded.status, "updated_at": func.now()},
        )
    )
    await session.commit()
    return ApplicationStatusRead(program_id=program_id, status=body.status)
