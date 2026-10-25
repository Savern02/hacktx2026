"""APR impact and the lender-request draft. Offline: Nessie and Gemini are faked."""

import pytest
from sqlalchemy import update

from app.finance import apr, service
from app.models import User
from app.services import gemini_service
from tests.test_finance import history_from_plan

TOYOTA = {
    "type": "auto",
    "status": "approved",
    "monthly_payment": 389,
    "amount": 14200,
    "credit_score": 590,
    "description": "Toyota auto loan",
}


def test_lender_name():
    assert apr.lender_name("Toyota auto loan") == "Toyota"
    assert (
        apr.lender_name("Toyota auto loan (24.99% APR)") == "Toyota"
    )  # older seed text


def test_monthly_interest_and_payoff_math():
    assert apr.monthly_interest(14200, 24.99) == pytest.approx(295.71, abs=0.01)
    months = apr.months_to_payoff(14200, 24.99, 389)
    assert 69 < months < 70
    assert apr.months_to_payoff(14200, 24.99, 290) is None  # payment < interest
    assert apr.months_to_payoff(1200, 0, 100) == 12

    plan = apr.payoff_plan(14200, 24.99, 389, extra=100)
    assert plan["months_now"] == 70 and plan["months_with_extra"] < plan["months_now"]
    assert plan["months_sooner"] == plan["months_now"] - plan["months_with_extra"]
    assert plan["interest_saved"] > 0
    assert apr.payoff_plan(14200, 24.99, 389, extra=0) is None


def test_every_approved_loan_gets_an_apr_from_the_published_ranges():
    loans = [
        TOYOTA,  # auto, 590 -> subprime
        {**TOYOTA, "description": "Honda loan", "credit_score": 610},  # auto, nonprime
        {**TOYOTA, "description": "Home mortgage", "type": "home", "credit_score": 765},
        {**TOYOTA, "status": "pending", "description": "Pending"},  # not approved
    ]
    out = apr.summarize_loans(loans)
    assert [(loan["name"], loan["apr"]) for loan in out] == [
        ("Toyota auto loan", 19.42),
        ("Honda loan", 14.03),
        ("Home mortgage", 6.70),
    ]
    assert out[0]["apr_basis"].startswith("Estimated from a 590 credit score")
    # A rate written into an old description is ignored: the table decides.
    old = apr.summarize_loans(
        [{**TOYOTA, "description": "Toyota auto loan (24.99% APR)"}]
    )
    assert (old[0]["name"], old[0]["apr"]) == ("Toyota auto loan", 19.42)


def test_estimate_apr_tiers():
    assert apr.estimate_apr("auto", 800)[0] == 6.30
    assert apr.estimate_apr("auto", 661)[0] == 8.77
    assert apr.estimate_apr("auto", 450)[0] == 21.77
    assert apr.estimate_apr("home", 765)[0] == 6.70
    assert apr.estimate_apr("home", 600)[0] == 7.36
    assert apr.estimate_apr("small business", 720)[0] == 8.90
    assert apr.estimate_apr("auto", None)[0] == 21.77  # no score: cautious side
    assert apr.estimate_apr("boat", 700)[0] == 8.77  # unknown type: auto table


async def _connect(db_session, user):
    await db_session.execute(
        update(User)
        .where(User.id == user.id)
        .values(nessie_customer_id="cust-1", full_name="Maria Lopez")
    )
    await db_session.commit()


@pytest.fixture
def fake_bank(monkeypatch):
    async def loans(user):
        return apr.summarize_loans([TOYOTA])

    async def raw_loans(user):
        return [TOYOTA, {**TOYOTA, "description": "Honda loan", "amount": 5000}]

    async def history(customer_id, merchants):
        return history_from_plan(customer_id)

    async def no_recs(session, user, refresh=False):
        raise RuntimeError("Gemini down")  # the utility card is optional

    monkeypatch.setattr(service, "get_apr_loans", loans)
    monkeypatch.setattr(service, "get_raw_loans", raw_loans)
    monkeypatch.setattr(service, "fetch_history", history)
    monkeypatch.setattr(service, "get_recommendations", no_recs)


async def test_apr_impact_endpoint(
    test_client, db_session, authenticated_user, fake_bank
):
    await _connect(db_session, authenticated_user["user"])
    r = await test_client.get(
        "/finance/me/apr-impact", headers=authenticated_user["headers"]
    )
    assert r.status_code == 200
    body = r.json()
    assert body["highest"]["apr"] == 19.42 and body["highest"][
        "monthly_interest"
    ] == pytest.approx(229.80, abs=0.01)
    assert body["utility_monthly"] > 0  # the seeded Electric bill
    plan = body["payoff_with_utility_help"]
    assert (
        plan["extra_monthly"] == body["utility_monthly"] and plan["months_sooner"] > 0
    )
    assert body["utility_program"] is None  # Gemini failure just omits the card
    # The Honda loan states no rate, so it gets an estimate instead of being dropped.
    honda = next(loan for loan in body["loans"] if loan["name"] == "Honda loan")
    assert honda["apr"] == 19.42  # Honda fixture shares the 590 score


async def test_apr_impact_needs_a_bank(test_client, authenticated_user):
    r = await test_client.get(
        "/finance/me/apr-impact", headers=authenticated_user["headers"]
    )
    assert r.status_code == 409


async def test_lender_request_draft_uses_only_given_facts(
    test_client, db_session, authenticated_user, fake_bank, monkeypatch
):
    await _connect(db_session, authenticated_user["user"])
    seen = {}

    async def fake_reply(system_prompt, messages):
        seen["system"], seen["user"] = system_prompt, messages[0].text
        return "Hello Toyota, ... Maria Lopez"

    monkeypatch.setattr(gemini_service, "generate_reply", fake_reply)
    r = await test_client.post(
        "/finance/me/lender-request", headers=authenticated_user["headers"]
    )
    assert r.status_code == 200
    assert r.json()["draft"].startswith("Hello Toyota")
    # The estimate is never presented to the lender as their actual rate.
    assert "[your current APR]" in seen["user"] and "19.42" not in seen["user"]
    assert "Maria Lopez" in seen["user"]
    assert (
        "Never invent" in seen["system"]
        and "keep this only if it's true" in seen["system"]
    )
