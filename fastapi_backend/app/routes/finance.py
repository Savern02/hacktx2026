"""Money check-up (50/30/20, 28/36) from Nessie, and Equa's program matches."""

import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.discovery.models import Jurisdiction, Program
from app.finance import advisor, apr, service
from app.finance.models import ProgramApplication
from app.models import User
from app.routes.programs import _program
from app.schemas import (
    ApplicationStatusRead,
    ApplicationStatusUpdate,
    AprImpact,
    AprLoan,
    ChatMessage,
    FinancialHealth,
    LenderRequest,
    PayoffPlan,
    ProgramMatch,
    ProgramMatches,
)
from app.services import gemini_service
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

    return ProgramMatches(
        summary=result["summary"],
        matches=await _matches(session, user, result),
        computed_at=result["computed_at"],
    )


async def _matches(
    session: AsyncSession, user: User, result: dict
) -> list[ProgramMatch]:
    """Equa's recommendations as full matches, with link and application status.

    Programs the user already applied to or dismissed always come back too, from
    their saved statuses, so a new set of recommendations never hides them.
    """
    status_rows = await session.execute(
        select(ProgramApplication.program_id, ProgramApplication.status).where(
            ProgramApplication.user_id == user.id
        )
    )
    # Not dict(result): SQLAlchemy results have .keys(), so dict() treats them as mappings.
    statuses = {pid: st for pid, st in status_rows.tuples()}
    recs = list(result["recommendations"])
    picked = {r["program_id"] for r in recs}
    recs += [
        {"program_id": pid, "reason": None, "confidence": 0.0}
        for pid, st in statuses.items()
        if st in ("complete", "not-applicable") and pid not in picked
    ]
    rows = await session.execute(
        select(Program, Jurisdiction)
        .join(Jurisdiction, Jurisdiction.id == Program.jurisdiction_id)
        .where(Program.id.in_([r["program_id"] for r in recs]))
    )
    by_id = {p.id: (p, j) for p, j in rows.tuples()}
    return [
        ProgramMatch(
            program=_program(*by_id[r["program_id"]]),
            # Backfilled programs have no saved reason, so describe the program.
            reason=advisor.short_reason(
                r["reason"]
                or by_id[r["program_id"]][0].summary
                or by_id[r["program_id"]][0].eligibility_summary
            ),
            confidence=r["confidence"],
            application_url=application_url(by_id[r["program_id"]][0]),
            application_status=statuses.get(r["program_id"], "in-progress"),
        )
        for r in recs
        if r["program_id"] in by_id
    ]


UTILITY_PROGRAM_RE = re.compile(
    r"energy|utilit|weatheriz|heating|electric|liheap", re.IGNORECASE
)


@router.get("/me/apr-impact", response_model=AprImpact)
async def get_my_apr_impact(
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """The user's highest-APR debt, what it costs, and how utility help could pay it down."""
    try:
        raw_loans = await service.get_raw_loans(user)
        health = await service.get_health(session, user)
    except service.NotConnected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="BANK_NOT_CONNECTED"
        )
    except NessieError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="BANK_UNAVAILABLE"
        )

    loans = apr.summarize_loans(raw_loans)
    highest = loans[0] if loans else None
    utilities = apr.utility_monthly(health)
    plan = (
        apr.payoff_plan(
            highest["balance"], highest["apr"], highest["monthly_payment"], utilities
        )
        if highest
        else None
    )

    # Only a program Equa already matched (so "may qualify" holds); Gemini
    # failures just leave the card out.
    utility_program = None
    try:
        result = await service.get_recommendations(session, user)
        utility_program = next(
            (
                m
                for m in await _matches(session, user, result)
                if UTILITY_PROGRAM_RE.search(m.program.name)
            ),
            None,
        )
    except Exception:
        utility_program = None

    return AprImpact(
        loans=[AprLoan(**loan) for loan in loans],
        highest=AprLoan(**highest) if highest else None,
        utility_monthly=utilities,
        payoff_with_utility_help=PayoffPlan(**plan) if plan else None,
        utility_program=utility_program,
    )


LENDER_REQUEST_PROMPT = """You help someone write a short, polite message to their lender asking for a lower interest rate or a penalty-free deferment (hardship) option.

Rules:
- Use only the facts given. Never invent account numbers, dates, payment history, income or hardship details.
- Where a fact is needed but not given, leave a bracketed placeholder, e.g. [your account number].
- Include the line "[I have made every payment on time — keep this only if it's true]".
- {ask}
- Plain, confident, friendly. Under 170 words. Plain text, no markdown. Start with "Hello" and end with the person's name."""


LENDER_ASKS = {
    "rate": "Ask for: a lower APR, and if that's not possible, a hardship or penalty-free deferment option.",
    "deferment": "Ask for: a one-month payment extension (a temporary-hardship deferral that moves this payment to the end of the loan), and ask whether it adds any charges, how it is reported to credit bureaus, and what other hardship options are available.",
}


@router.post("/me/lender-request", response_model=LenderRequest)
async def draft_my_lender_request(
    goal: Literal["rate", "deferment"] = Query(default="rate"),
    user: User = Depends(current_active_user),
):
    """Equa (Gemini) drafts a rate-reduction or deferment request for the highest-APR loan."""
    try:
        loans = await service.get_apr_loans(user)
    except service.NotConnected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="BANK_NOT_CONNECTED"
        )
    except NessieError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="BANK_UNAVAILABLE"
        )
    if not loans:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NO_APR_LOAN")
    loan = loans[0]
    facts = (
        f"Person's name: {user.full_name or '[your name]'}\n"
        f"Lender: {loan['lender']}\n"
        f"Loan: {loan['name']} ({loan['type']})\n"
        f"Balance: ${loan['balance']:,.0f}\n"
        f"Monthly payment: ${loan['monthly_payment']:,.0f}\n"
        # The APR is an estimate from credit score, not a fact about their loan:
        # leave it for them to fill in from their statement.
        + "Current APR: not known; use the placeholder [your current APR]"
    )
    try:
        draft = await gemini_service.generate_reply(
            LENDER_REQUEST_PROMPT.replace("{ask}", LENDER_ASKS[goal]),
            [ChatMessage(role="user", text=f"Write the message.\n\n{facts}")],
        )
    except gemini_service.GeminiError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="ADVISOR_UNAVAILABLE"
        )
    return LenderRequest(loan=AprLoan(**loan), draft=draft)


@router.put("/me/applications/{program_id}", response_model=ApplicationStatusRead)
async def set_my_application_status(
    program_id: int,
    body: ApplicationStatusUpdate,
    session: AsyncSession = Depends(get_async_session),
    user: User = Depends(current_active_user),
):
    """Mark a matched program's application as in progress, complete, or not applicable."""
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
