"""APR impact: what a user's highest-rate debt costs them, from Nessie loans.

Nessie loans have no rate field, only a credit_score. Every loan's APR comes from
its credit_score and type, using the published averages in APR_TIERS.
"""

import math
import re
from typing import Any

# Strips a rate written into an older description, e.g. "(24.99% APR)".
APR_RE = re.compile(r"(\d{1,2}(?:\.\d{1,2})?)\s*%\s*APR", re.IGNORECASE)
UTILITY_RE = re.compile(r"electric|energy|utilit|water|gas bill|power", re.IGNORECASE)


def lender_name(description: str) -> str:
    """'Toyota auto loan (24.99% APR)' -> 'Toyota'."""
    name = APR_RE.sub("", description).replace("()", "").strip()
    name = re.sub(
        r"\b(auto|car|personal|student|home)?\s*loan\b.*$", "", name, flags=re.I
    ).strip()
    return name or "your lender"


def monthly_interest(balance: float, apr: float) -> float:
    return balance * apr / 1200


def months_to_payoff(balance: float, apr: float, payment: float) -> float | None:
    """Standard amortization. None when the payment doesn't even cover the interest."""
    r = apr / 1200
    if payment <= 0:
        return None
    if r == 0:
        return balance / payment
    if payment <= balance * r:
        return None
    return -math.log(1 - r * balance / payment) / math.log(1 + r)


def payoff_plan(
    balance: float, apr: float, payment: float, extra: float
) -> dict[str, Any] | None:
    """How much sooner and cheaper the loan ends if `extra` goes to it every month."""
    now = months_to_payoff(balance, apr, payment)
    faster = months_to_payoff(balance, apr, payment + extra)
    if now is None or faster is None or extra <= 0:
        return None
    interest_now = payment * now - balance
    interest_faster = (payment + extra) * faster - balance
    return {
        "extra_monthly": round(extra, 2),
        "months_now": math.ceil(now),
        "months_with_extra": math.ceil(faster),
        "months_sooner": max(math.ceil(now) - math.ceil(faster), 0),
        "interest_saved": round(max(interest_now - interest_faster, 0), 2),
    }


# Nessie loans carry no interest rate, only a credit_score, and lenders price by
# credit tier. These published averages are the only source of APRs in Equa.
# Tiers are (minimum score, APR %), highest score first.
APR_TIERS: dict[str, tuple[tuple[int, float], ...]] = {
    # Experian, State of the Automotive Finance Market, Q1 2026: used-car averages
    # by VantageScore tier (used, because new vs used isn't known; it's the higher one).
    "auto": ((781, 6.30), (661, 8.77), (601, 14.03), (501, 19.42), (0, 21.77)),
    # myFICO 30-year fixed APR by FICO score (620-639 is the lowest tier published).
    "home": (
        (760, 6.70),
        (700, 6.95),
        (680, 7.07),
        (660, 7.11),
        (640, 7.21),
        (0, 7.36),
    ),
    # No per-score table exists for business loans. Rough mapping onto published
    # ranges: bank term loans 6.8-11% (Fed, Q1 2026), SBA 7(a) 9.75-14.75%.
    "small business": ((700, 8.90), (620, 12.25), (0, 14.75)),
}
TIER_SOURCES = {
    "auto": "Experian Q1 2026 used-car averages",
    "home": "myFICO 30-year mortgage averages",
    "small business": "Federal Reserve and SBA business-loan ranges",
}


def estimate_apr(loan_type: str | None, credit_score: int | None) -> tuple[float, str]:
    """(APR %, short explanation) for a loan of this type and credit score."""
    kind = (loan_type or "auto").lower()
    tiers = APR_TIERS.get(kind, APR_TIERS["auto"])
    score = credit_score or 0  # no score: assume the lowest tier, the cautious side
    apr = next(rate for minimum, rate in tiers if score >= minimum)
    basis = (
        f"Estimated from a {credit_score} credit score"
        if credit_score
        else "Estimated (no credit score on file)"
    )
    return apr, f"{basis} ({TIER_SOURCES.get(kind, TIER_SOURCES['auto'])})"


def summarize_loans(loans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Approved loans with their estimated APR, highest APR first."""
    out = []
    for loan in loans:
        if loan.get("status") != "approved":
            continue
        rate, basis = estimate_apr(loan.get("type"), loan.get("credit_score"))
        balance = float(loan.get("amount") or 0)
        payment = float(loan.get("monthly_payment") or 0)
        description = loan.get("description") or f"{loan.get('type', '')} loan"
        out.append(
            {
                "name": APR_RE.sub("", description).replace("()", "").strip(),
                "lender": lender_name(description),
                "type": loan.get("type") or "loan",
                "apr": rate,
                "apr_basis": basis,
                "balance": round(balance, 2),
                "monthly_payment": round(payment, 2),
                "monthly_interest": round(monthly_interest(balance, rate), 2),
            }
        )
    return sorted(out, key=lambda loan: loan["apr"], reverse=True)


def utility_monthly(health: dict[str, Any] | None) -> float:
    """Monthly utility bills from the money check-up (e.g. Electric)."""
    if not health:
        return 0.0
    return round(
        sum(
            c["monthly"]
            for c in health.get("categories", [])
            if c["bucket"] == "needs" and UTILITY_RE.search(c["label"])
        ),
        2,
    )
