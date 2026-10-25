"""Money check-up (50/30/20, 28/36) and Equa's program matches. Offline: Nessie and Gemini are faked."""

from datetime import date

import httpx
from sqlalchemy import update

from app.discovery.models import Jurisdiction, Program
from app.finance import advisor, service
from app.finance.demo_history import DEMO_MERCHANTS, plan_history
from app.finance.metrics import History, compute_health
from app.models import User

TODAY = date(2026, 10, 25)


def history_from_plan(seed: str = "cust-1") -> History:
    plan = plan_history(seed, TODAY)
    return History(
        deposits=[
            {
                "status": "completed",
                "transaction_date": d["day"].isoformat(),
                "amount": d["amount"],
            }
            for d in plan["deposits"]
        ],
        purchases=[
            {
                "status": "completed",
                "purchase_date": p.day.isoformat(),
                "amount": p.amount,
                "category": DEMO_MERCHANTS[p.merchant],
            }
            for p in plan["purchases"]
        ],
        bills=[
            {
                "status": "recurring",
                "nickname": b["nickname"],
                "payee": b["payee"],
                "payment_amount": b["amount"],
            }
            for b in plan["bills"]
        ],
        loans=[{"status": "approved", **plan["loan"]}],
    )


def test_demo_history_is_deterministic_and_whole_dollars():
    a, b = plan_history("cust-1", TODAY), plan_history("cust-1", TODAY)
    assert [p.amount for p in a["purchases"]] == [p.amount for p in b["purchases"]]
    assert all(
        isinstance(p.amount, int) for p in a["purchases"]
    )  # Nessie stores integers
    assert plan_history("cust-2", TODAY)["deposits"][0]["amount"] != 0
    assert {p.merchant for p in a["purchases"]} <= set(DEMO_MERCHANTS)


def test_rules_from_a_stretched_history():
    h = compute_health(history_from_plan(), TODAY.isoformat())
    r1, r2 = h["rule_50_30_20"], h["rule_28_36"]
    assert h["income_monthly"] > 2000
    assert not r1["needs"]["ok"] and r1["needs"]["pct"] > 50
    assert r1["wants"]["ok"]
    assert not r1["savings"]["ok"]
    assert r2["housing"]["amount"] == 1150 and not r2["housing"]["ok"]
    assert r2["debt"]["amount"] == 1150 + 389 and not r2["debt"]["ok"]
    assert set(h["struggling"]) == {"needs", "savings", "housing", "debt"}
    rent = next(c for c in h["categories"] if c["label"] == "Rent")
    assert rent["bucket"] == "housing"


def test_buckets_and_window():
    h = History(
        deposits=[
            {"status": "completed", "transaction_date": "2026-10-01", "amount": 3000},
            {
                "status": "completed",
                "transaction_date": "2026-06-01",
                "amount": 99999,
            },  # outside window
            {
                "status": "pending",
                "transaction_date": "2026-10-02",
                "amount": 5000,
            },  # not completed
        ],
        purchases=[
            {
                "status": "completed",
                "purchase_date": "2026-10-03",
                "amount": 120,
                "category": "Restaurants",
            }
        ],
        bills=[
            {
                "status": "recurring",
                "payee": "Oak Lane Mortgage",
                "nickname": "House",
                "payment_amount": 800,
            }
        ],
        loans=[
            {
                "status": "approved",
                "type": "home",
                "monthly_payment": 0,
                "description": "Home",
            }
        ],
    )
    out = compute_health(h, TODAY.isoformat())
    assert out["income_monthly"] == round(
        3000 / (56 * 12 / 365), 2
    )  # 3000 over an 8-week window
    assert (
        out["rule_28_36"]["housing"]["amount"] == 800
    )  # 'mortgage' in payee -> housing
    assert out["rule_50_30_20"]["wants"]["amount"] == round(120 / (56 * 12 / 365), 2)


def test_no_income_means_unknown_not_ok():
    out = compute_health(History([], [], [], []), TODAY.isoformat())
    assert (
        out["rule_50_30_20"]["needs"]["pct"] is None
        and not out["rule_50_30_20"]["needs"]["ok"]
    )


def test_advisor_keeps_only_listed_programs():
    raw = {
        "summary": "Housing is the big squeeze.",
        "recommendations": [
            {"program_id": 1, "reason": "Rent is 42% of income.", "confidence": 0.9},
            {
                "program_id": 999,
                "reason": "Invented program.",
                "confidence": 0.99,
            },  # not a candidate
            {"program_id": 1, "reason": "Duplicate.", "confidence": 0.8},
            {"program_id": 2, "reason": "Weak fit.", "confidence": 0.1},  # too unsure
            {"program_id": "x", "reason": "Bad id.", "confidence": 0.9},
        ]
        + [{"program_id": i, "reason": "ok", "confidence": 0.5} for i in range(3, 10)],
    }
    out = advisor.validate(raw, candidate_ids=set(range(1, 10)))
    ids = [r["program_id"] for r in out["recommendations"]]
    assert (
        ids[0] == 1
        and 999 not in ids
        and 2 not in ids
        and len(ids) == 5
        and len(set(ids)) == 5
    )


def test_short_reason_is_one_short_sentence():
    assert advisor.short_reason("Rent is high. You may qualify.") == "Rent is high."
    long = "Your rent is 48% of your take-home income, so you may qualify for rental help from this program and more"
    out = advisor.short_reason(long)
    assert len(out) <= advisor.REASON_MAX_CHARS and out.endswith("…")
    assert not out[:-1].endswith((" ", ",", " and", " for"))
    assert advisor.short_reason(None) == ""


def test_advisor_message_lists_candidates_and_numbers():
    h = compute_health(history_from_plan(), TODAY.isoformat())
    msg = advisor.build_message(
        h,
        [
            {
                "id": 7,
                "name": "SNAP",
                "jurisdiction": "Federal",
                "eligibility": "Low-income households.",
            }
        ],
    )
    assert "[7] SNAP (Federal): Low-income households." in msg
    assert "Housing:" in msg and "STRUGGLING" in msg
    assert (
        "never" in advisor.SYSTEM_PROMPT.lower()
        and "may qualify" in advisor.SYSTEM_PROMPT
    )


async def test_advisor_calls_gemini_with_a_forced_tool(monkeypatch):
    monkeypatch.setattr(advisor.settings, "GEMINI_KEY", "test-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read().decode()
        args = {
            "summary": "s",
            "recommendations": [
                {"program_id": 7, "reason": "Rent is high.", "confidence": 0.7}
            ],
        }
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "recommend_programs",
                                        "args": args,
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    h = compute_health(history_from_plan(), TODAY.isoformat())
    out = await advisor.recommend(
        h,
        [{"id": 7, "name": "SNAP", "jurisdiction": "Federal"}],
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert out["recommendations"] == [
        {"program_id": 7, "reason": "Rent is high.", "confidence": 0.7}
    ]
    assert (
        '"mode":"ANY"' in seen["body"].replace(" ", "")
        and "recommend_programs" in seen["body"]
    )


async def test_health_endpoint_needs_a_bank(test_client, authenticated_user):
    r = await test_client.get(
        "/finance/me/health", headers=authenticated_user["headers"]
    )
    assert r.status_code == 409 and r.json()["detail"] == "BANK_NOT_CONNECTED"


async def _connect(db_session, user: User) -> None:
    await db_session.execute(
        update(User).where(User.id == user.id).values(nessie_customer_id="cust-1")
    )
    await db_session.commit()


async def test_health_is_cached(
    test_client, db_session, authenticated_user, monkeypatch
):
    await _connect(db_session, authenticated_user["user"])
    calls = []

    async def fake_fetch(customer_id, merchants):
        calls.append(customer_id)
        return history_from_plan(customer_id)

    monkeypatch.setattr(service, "fetch_history", fake_fetch)
    monkeypatch.setattr(
        service, "date", type("D", (), {"today": staticmethod(lambda: TODAY)})
    )
    h = authenticated_user["headers"]
    first = await test_client.get("/finance/me/health", headers=h)
    second = await test_client.get("/finance/me/health", headers=h)
    assert first.status_code == 200 and first.json() == second.json()
    assert calls == ["cust-1"]  # second call came from the cache
    assert (
        await test_client.get("/finance/me/health?refresh=true", headers=h)
    ).status_code == 200
    assert calls == ["cust-1", "cust-1"]


async def test_program_matches_only_return_visible_programs(
    test_client, db_session, authenticated_user, monkeypatch
):
    federal = Jurisdiction(
        level="federal", name="United States", display_name="Federal"
    )
    db_session.add(federal)
    await db_session.flush()
    visible = Program(
        jurisdiction_id=federal.id,
        name="SNAP",
        normalized_name="snap",
        audience="individual",
        review_status="published",
        origin="seed_sam_gov",
        eligibility_summary="Low-income households.",
    )
    hidden = Program(
        jurisdiction_id=federal.id,
        name="Grants to States",
        normalized_name="grants",
        audience="government",
        review_status="published",
        origin="seed_sam_gov",
        eligibility_summary="States.",
    )
    db_session.add_all([visible, hidden])
    await db_session.commit()
    await _connect(db_session, authenticated_user["user"])

    async def fake_fetch(customer_id, merchants):
        return history_from_plan(customer_id)

    sent = {}

    async def fake_recommend(health, candidates):
        sent["ids"] = {c["id"] for c in candidates}
        return advisor.validate(
            {
                "summary": "Rent is the squeeze.",
                "recommendations": [
                    {
                        "program_id": visible.id,
                        "reason": "Groceries take a big share.",
                        "confidence": 0.8,
                    },
                    {
                        "program_id": hidden.id,
                        "reason": "Not for people.",
                        "confidence": 0.9,
                    },
                ],
            },
            sent["ids"],
        )

    monkeypatch.setattr(service, "fetch_history", fake_fetch)
    monkeypatch.setattr(service.advisor, "recommend", fake_recommend)
    r = await test_client.get(
        "/finance/me/program-matches", headers=authenticated_user["headers"]
    )
    assert r.status_code == 200
    body = r.json()
    assert sent["ids"] == {visible.id}  # hidden programs are never offered to Gemini
    assert [m["program"]["name"] for m in body["matches"]] == ["SNAP"]
    assert body["summary"] == "Rent is the squeeze."


def test_application_url_only_returns_real_links():
    from app.routes.finance import application_url

    def p(apply_url=None, info_url=None):
        return Program(
            name="x",
            normalized_name="x",
            audience="individual",
            origin="admin",
            apply_url=apply_url,
            info_url=info_url,
        )

    assert (
        application_url(p("https://www.benefits.gov/apply", "https://x.gov"))
        == "https://www.benefits.gov/apply"
    )
    assert (
        application_url(p("www.fns.usda.gov/snap", "https://www.fns.usda.gov/snap"))
        == "https://www.fns.usda.gov/snap"
    )
    assert application_url(p("javascript:alert(1)", None)) is None
    assert application_url(p(None, "http://localhost/apply")) is None
    assert application_url(p()) is None


async def test_matches_carry_application_status_that_users_can_update(
    test_client, db_session, authenticated_user, monkeypatch
):
    federal = Jurisdiction(
        level="federal", name="United States", display_name="Federal"
    )
    db_session.add(federal)
    await db_session.flush()
    snap = Program(
        jurisdiction_id=federal.id,
        name="SNAP",
        normalized_name="snap",
        audience="individual",
        review_status="published",
        origin="seed_sam_gov",
        eligibility_summary="Low-income households.",
        info_url="https://www.fns.usda.gov/snap",
    )
    hidden = Program(
        jurisdiction_id=federal.id,
        name="Unvetted",
        normalized_name="unvetted",
        audience="individual",
        review_status="needs_review",
        origin="seed_sam_gov",
    )
    db_session.add_all([snap, hidden])
    await db_session.commit()
    await _connect(db_session, authenticated_user["user"])

    async def fake_fetch(customer_id, merchants):
        return history_from_plan(customer_id)

    async def fake_recommend(health, candidates):
        return {
            "summary": "s",
            "recommendations": [
                {
                    "program_id": snap.id,
                    "reason": "Groceries are high.",
                    "confidence": 0.8,
                }
            ],
        }

    monkeypatch.setattr(service, "fetch_history", fake_fetch)
    monkeypatch.setattr(service.advisor, "recommend", fake_recommend)
    h = authenticated_user["headers"]

    match = (await test_client.get("/finance/me/program-matches", headers=h)).json()[
        "matches"
    ][0]
    assert (match["application_status"], match["application_url"]) == (
        "in-progress",
        "https://www.fns.usda.gov/snap",
    )

    r = await test_client.put(
        f"/finance/me/applications/{snap.id}", headers=h, json={"status": "complete"}
    )
    assert r.status_code == 200 and r.json() == {
        "program_id": snap.id,
        "status": "complete",
    }
    match = (await test_client.get("/finance/me/program-matches", headers=h)).json()[
        "matches"
    ][0]
    assert match["application_status"] == "complete"

    assert (
        await test_client.put(
            f"/finance/me/applications/{snap.id}", headers=h, json={"status": "maybe"}
        )
    ).status_code == 422
    assert (
        await test_client.put(
            f"/finance/me/applications/{hidden.id}",
            headers=h,
            json={"status": "complete"},
        )
    ).status_code == 404
    assert (
        await test_client.put(
            "/finance/me/applications/999999", headers=h, json={"status": "complete"}
        )
    ).status_code == 404


async def test_asking_again_keeps_programs_the_user_already_handled(
    test_client, db_session, authenticated_user, monkeypatch
):
    federal = Jurisdiction(
        level="federal", name="United States", display_name="Federal"
    )
    db_session.add(federal)
    await db_session.flush()

    def program(name):
        return Program(
            jurisdiction_id=federal.id,
            name=name,
            normalized_name=name.lower(),
            audience="individual",
            review_status="published",
            origin="seed_sam_gov",
            eligibility_summary="Low-income households.",
        )

    snap, liheap, wic = program("SNAP"), program("LIHEAP"), program("WIC")
    db_session.add_all([snap, liheap, wic])
    await db_session.commit()
    await _connect(db_session, authenticated_user["user"])

    async def fake_fetch(customer_id, merchants):
        return history_from_plan(customer_id)

    picks = [snap.id, liheap.id]
    offered = {}

    async def fake_recommend(health, candidates):
        offered["ids"] = {c["id"] for c in candidates}
        return {
            "summary": "s",
            "recommendations": [
                {"program_id": pid, "reason": f"r{pid}", "confidence": 0.8}
                for pid in picks
            ],
        }

    monkeypatch.setattr(service, "fetch_history", fake_fetch)
    monkeypatch.setattr(service.advisor, "recommend", fake_recommend)
    h = authenticated_user["headers"]
    url = "/finance/me/program-matches"

    await test_client.get(url, headers=h)
    await test_client.put(
        f"/finance/me/applications/{snap.id}", headers=h, json={"status": "complete"}
    )
    await test_client.put(
        f"/finance/me/applications/{liheap.id}",
        headers=h,
        json={"status": "not-applicable"},
    )

    picks[:] = [wic.id]  # Equa picks something new this time
    body = (await test_client.get(f"{url}?refresh=true", headers=h)).json()

    assert liheap.id not in offered["ids"]  # dismissed programs aren't re-offered
    assert [
        (m["program"]["name"], m["application_status"], m["reason"])
        for m in body["matches"]
    ] == [
        ("WIC", "in-progress", f"r{wic.id}"),
        ("SNAP", "complete", f"r{snap.id}"),
        ("LIHEAP", "not-applicable", f"r{liheap.id}"),
    ]

    # Even if Equa picks handled programs again, it can't revive them as in-progress,
    # and asking again (twice) never touches the saved rows.
    picks[:] = [snap.id, liheap.id, wic.id]
    body = (await test_client.get(f"{url}?refresh=true", headers=h)).json()
    statuses = {m["program"]["name"]: m["application_status"] for m in body["matches"]}
    assert statuses == {
        "SNAP": "complete",
        "LIHEAP": "not-applicable",
        "WIC": "in-progress",
    }
    body = (await test_client.get(url, headers=h)).json()  # a plain reload
    assert {
        m["program"]["name"]: m["application_status"] for m in body["matches"]
    } == statuses


async def test_handled_programs_show_even_without_a_saved_recommendation(
    test_client, db_session, authenticated_user, monkeypatch
):
    federal = Jurisdiction(
        level="federal", name="United States", display_name="Federal"
    )
    db_session.add(federal)
    await db_session.flush()
    snap = Program(
        jurisdiction_id=federal.id,
        name="SNAP",
        normalized_name="snap",
        audience="individual",
        review_status="published",
        origin="seed_sam_gov",
        summary="Help buying groceries.",
    )
    db_session.add(snap)
    await db_session.commit()
    await _connect(db_session, authenticated_user["user"])

    async def fake_fetch(customer_id, merchants):
        return history_from_plan(customer_id)

    async def fake_recommend(health, candidates):
        return {"summary": "s", "recommendations": []}  # Equa picks nothing

    monkeypatch.setattr(service, "fetch_history", fake_fetch)
    monkeypatch.setattr(service.advisor, "recommend", fake_recommend)
    h = authenticated_user["headers"]
    await test_client.put(
        f"/finance/me/applications/{snap.id}",
        headers=h,
        json={"status": "not-applicable"},
    )

    body = (
        await test_client.get("/finance/me/program-matches?refresh=true", headers=h)
    ).json()
    assert [
        (m["program"]["name"], m["application_status"], m["reason"])
        for m in body["matches"]
    ] == [("SNAP", "not-applicable", "Help buying groceries.")]
