from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.discovery.models import Program
from app.finance.models import FinancialInsight
from app.models import User
from app.routes.balance import get_upcoming_bills
from app.schemas import ChatRequest, ChatResponse
from app.services import gemini_service, nessie_service
from app.users import current_active_user

router = APIRouter(tags=["chat"])

EQUA_PROMPT = """You are Equa, a friendly money helper inside the Equa app ("Have a problem? Use Equa.").
Your users are often under financial stress. Be warm, calm and encouraging, never judgmental.

How you talk:
- Plain, simple words at about a 6th-grade reading level. No jargon; explain any money term you must use.
- Short: 2 to 4 sentences, readable on a phone. Use a short list only when giving steps.
- Always end with one clear next step the user can take.
- Plain text only, no markdown headings or tables.

What the app has, so you can point people to it:
- Overview tab: "Safe to Spend" (checking balance minus upcoming bills) and spending rings per category.
- Programs tab: tracks applications for government benefits such as SNAP, LIHEAP, Medicaid, Lifeline and WIC.

Rules:
- You are not a licensed financial, legal or tax advisor. For big decisions, suggest talking to a nonprofit credit counselor or calling 211 in the US.
- Never ask for passwords, full card or account numbers, or Social Security numbers.
- If someone mentions being in danger or crisis, gently share 988 (Suicide & Crisis Lifeline) or 911.
- Don't invent numbers. Only use the user's figures given below."""


async def build_user_context(session: AsyncSession, user: User) -> str:
    if user.nessie_customer_id is None:
        return "No bank account is linked yet."
    try:
        balance = await nessie_service.get_checking_balance(user.nessie_customer_id)
        bills = await get_upcoming_bills(user.nessie_customer_id)
    except nessie_service.NessieError:
        return "The user's bank data is unavailable right now."
    bills_total = sum(b.amount for b in bills)
    bill_lines = "\n".join(
        f"- {b.name}: ${b.amount:,.2f} due {b.due_date:%b %d}" for b in bills
    )
    context = (
        f"Checking balance: ${balance:,.2f}\n"
        f"Upcoming bills:\n{bill_lines or '- none'}\n"
        f"Safe to Spend (balance minus bills): ${balance - bills_total:,.2f}"
    )
    insight = await session.get(FinancialInsight, user.id)
    if insight and insight.nessie_customer_id == user.nessie_customer_id:
        h = insight.health
        checks = {**h["rule_50_30_20"], **h["rule_28_36"]}
        context += (
            f"\nTake-home income: ${h['income_monthly']:,.0f}/month\n"
            + "\n".join(
                f"- {name}: {c['pct']}% of income (target {c['target']}%) {'OK' if c['ok'] else 'over'}"
                for name, c in checks.items()
            )
        )
        recs = (insight.recommendations or {}).get("recommendations") or []
        if recs:
            names = (
                await session.execute(
                    select(Program.name).where(
                        Program.id.in_([r["program_id"] for r in recs])
                    )
                )
            ).scalars()
            context += (
                "\nEqua already suggested these programs on the Overview tab: "
                + "; ".join(names)
            )
    return context


@router.post("", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    system_prompt = EQUA_PROMPT
    if user.first_name:
        system_prompt += (
            f"\n\nThe user's first name is {user.first_name}. Use it now and then "
            "to keep things warm and personal, but not in every message."
        )
    system_prompt += (
        f"\n\nThe user's current finances:\n"
        f"{await build_user_context(session, user)}"
    )
    try:
        reply = await gemini_service.generate_reply(system_prompt, request.messages)
    except gemini_service.GeminiError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return ChatResponse(reply=reply)
