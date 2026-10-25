"""Money check-up (50/30/20, 28/36) from Nessie, and Equa's program matches."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.discovery.models import Jurisdiction, Program
from app.finance import service
from app.models import User
from app.routes.programs import _program
from app.schemas import FinancialHealth, ProgramMatch, ProgramMatches
from app.services.nessie_service import NessieError
from app.users import current_active_user

router = APIRouter(tags=["finance"])


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
    return ProgramMatches(
        summary=result["summary"],
        matches=[
            ProgramMatch(
                program=_program(*by_id[r["program_id"]]),
                reason=r["reason"],
                confidence=r["confidence"],
            )
            for r in result["recommendations"]
            if r["program_id"] in by_id
        ],
        computed_at=result["computed_at"],
    )
