"""50/30/20 and 28/36 from a Nessie transaction history.

- 50/30/20: needs <= 50% of take-home income, wants <= 30%, savings >= 20%.
  Needs include housing, utilities, groceries, gas, health and minimum debt payments.
- 28/36: housing <= 28% of income, housing + debt payments <= 36%.
  The rule uses gross income; we only see deposits (take-home), so the ratios are
  conservative (a little high), which is the safer direction for this audience.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.services import nessie_service

# 8 weeks: always exactly four biweekly (or eight weekly) paychecks, so income
# doesn't swing 25% depending on where the window starts.
WINDOW_DAYS = 56

CATEGORY_BUCKET = {
    "groceries": "needs",
    "gas": "needs",
    "transportation": "needs",
    "pharmacy": "needs",
    "health": "needs",
    "utilities": "needs",
    "restaurants": "wants",
    "dining": "wants",
    "shopping": "wants",
    "entertainment": "wants",
}
HOUSING_WORDS = ("rent", "mortgage", "apartment", "housing", "lease")


@dataclass
class History:
    deposits: list[dict[str, Any]]
    purchases: list[dict[str, Any]]  # each with a resolved "category"
    bills: list[dict[str, Any]]
    loans: list[dict[str, Any]]


async def fetch_history(
    customer_id: str, merchant_categories: dict[str, str]
) -> History:
    """All checking accounts' history. merchant_categories caches merchant_id -> category."""
    out = History([], [], [], [])
    for account_id in await nessie_service.checking_account_ids(customer_id):
        out.deposits += await nessie_service.list_account_resource(
            account_id, "deposits"
        )
        out.bills += await nessie_service.list_account_resource(account_id, "bills")
        out.loans += await nessie_service.list_account_resource(account_id, "loans")
        for p in await nessie_service.list_account_resource(account_id, "purchases"):
            mid = p.get("merchant_id")
            if mid and mid not in merchant_categories:
                merchant = await nessie_service.get_merchant(mid)
                merchant_categories[mid] = str(merchant.get("category") or "Other")
            out.purchases.append(
                {**p, "category": merchant_categories.get(mid or "", "Other")}
            )
    return out


def _pct(amount: float, income: float) -> float | None:
    return round(100 * amount / income, 1) if income > 0 else None


def compute_health(
    history: History, today_iso: str, window_days: int = WINDOW_DAYS
) -> dict[str, Any]:
    """Pure: monthly averages over the window, both rules, and notable items."""
    from datetime import date, timedelta

    today = date.fromisoformat(today_iso)
    start = today - timedelta(days=window_days)
    months = window_days * 12 / 365

    def in_window(day: str | None) -> bool:
        return bool(day) and start < date.fromisoformat(day[:10]) <= today

    income = (
        sum(
            d["amount"]
            for d in history.deposits
            if d.get("status") == "completed" and in_window(d.get("transaction_date"))
        )
        / months
    )

    lines: dict[tuple[str, str], float] = defaultdict(
        float
    )  # (label, bucket) -> monthly
    for p in history.purchases:
        if p.get("status") == "completed" and in_window(p.get("purchase_date")):
            bucket = CATEGORY_BUCKET.get(p["category"].lower(), "wants")
            lines[(p["category"], bucket)] += p["amount"] / months

    housing = 0.0
    for b in history.bills:
        if b.get("status") != "recurring":
            continue
        label = b.get("nickname") or b.get("payee") or "Bill"
        is_housing = any(
            w in f"{label} {b.get('payee', '')}".lower() for w in HOUSING_WORDS
        )
        lines[(label, "housing" if is_housing else "needs")] += b["payment_amount"]
        if is_housing:
            housing += b["payment_amount"]

    debt = 0.0
    for loan in history.loans:
        if loan.get("status") != "approved":
            continue
        label = loan.get("description") or f"{loan.get('type', 'loan')} loan"
        if loan.get("type") == "home":
            lines[(label, "housing")] += loan["monthly_payment"]
            housing += loan["monthly_payment"]
        else:
            lines[(label, "debt")] += loan["monthly_payment"]
            debt += loan["monthly_payment"]

    needs = sum(
        v for (_, bucket), v in lines.items() if bucket in ("needs", "housing", "debt")
    )
    wants = sum(v for (_, bucket), v in lines.items() if bucket == "wants")
    savings = income - needs - wants

    def rule(amount: float, limit: float, *, at_least: bool = False) -> dict[str, Any]:
        pct = _pct(amount, income)
        ok = pct is not None and (pct >= limit if at_least else pct <= limit)
        return {"amount": round(amount, 2), "pct": pct, "target": limit, "ok": ok}

    rules = {
        "needs": rule(needs, 50),
        "wants": rule(wants, 30),
        "savings": rule(savings, 20, at_least=True),
        "housing": rule(housing, 28),
        "debt": rule(housing + debt, 36),
    }
    categories = sorted(
        (
            {"label": label, "bucket": bucket, "monthly": round(v, 2)}
            for (label, bucket), v in lines.items()
        ),
        key=lambda c: c["monthly"],
        reverse=True,
    )
    return {
        "window_days": window_days,
        "income_monthly": round(income, 2),
        "income_note": "Based on deposits into checking (take-home pay).",
        "rule_50_30_20": {k: rules[k] for k in ("needs", "wants", "savings")},
        "rule_28_36": {k: rules[k] for k in ("housing", "debt")},
        "categories": categories,
        "struggling": [k for k, v in rules.items() if not v["ok"]],
    }
