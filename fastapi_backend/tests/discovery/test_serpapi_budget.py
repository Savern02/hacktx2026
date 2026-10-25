from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.discovery.models import SerpApiRequest
from app.discovery.serpapi_client import BudgetBlocked, SerpApiClient, SerpApiPaused

NOW = datetime(2026, 10, 24, 15, 30, tzinfo=timezone.utc)
ACCOUNT = {
    "total_searches_left": 1000,
    "this_hour_searches": 0,
    "account_rate_limit_per_hour": 100,
    "plan_renewal_date": "2026-11-24",
}
SEARCH_OK = {
    "search_metadata": {"id": "abc", "status": "Success"},
    "search_information": {"organic_results_state": "Results for exact spelling"},
    "organic_results": [{"link": "https://www.austintexas.gov/cap"}],
}


def client(
    session, *, account=None, search=None, cap=12, budget=100, reserve=50, calls=None
):
    calls = calls if calls is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/account.json":
            return httpx.Response(200, json=account or ACCOUNT)
        status, body = search or (200, SEARCH_OK)
        return httpx.Response(status, json=body)

    async def no_sleep(_):
        return None

    return SerpApiClient(
        session,
        api_key="SECRET-KEY",
        monthly_budget=budget,
        reserve=reserve,
        per_job_cap=cap,
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=no_sleep,
        clock=lambda: NOW,
    )


async def test_search_logs_without_api_key_and_replays_for_free(db_session):
    calls: list[httpx.Request] = []
    serp = client(db_session, calls=calls)
    first = await serp.search("austin rent help", "Austin,Texas,United States")
    assert first and not first.reused and serp.searches_used == 1
    row = await db_session.scalar(select(SerpApiRequest))
    assert "api_key" not in row.params and "SECRET-KEY" not in str(row.raw_response)
    assert row.serpapi_search_id == "abc" and row.organic_count == 1

    searches_before = sum(1 for c in calls if c.url.path == "/search.json")
    again = await serp.search("austin rent help", "Austin,Texas,United States")
    assert again and again.reused and serp.searches_used == 1
    assert sum(1 for c in calls if c.url.path == "/search.json") == searches_before


async def test_search_params_follow_the_rules(db_session):
    calls: list[httpx.Request] = []
    await client(db_session, calls=calls).search("q", "Austin,Texas,United States")
    params = dict(next(c for c in calls if c.url.path == "/search.json").url.params)
    assert {k: params[k] for k in ("engine", "gl", "hl", "device")} == {
        "engine": "google",
        "gl": "us",
        "hl": "en",
        "device": "desktop",
    }
    assert not {"num", "no_cache", "async"} & set(params)


async def test_blocks_at_reserve(db_session):
    serp = client(db_session, account={**ACCOUNT, "total_searches_left": 50})
    with pytest.raises(BudgetBlocked) as exc:
        await serp.search("q", None)
    assert exc.value.until == datetime(2026, 11, 24, tzinfo=timezone.utc)


async def test_blocks_at_90_percent_of_hourly_throughput(db_session):
    serp = client(db_session, account={**ACCOUNT, "this_hour_searches": 90})
    with pytest.raises(BudgetBlocked) as exc:
        await serp.search("q", None)
    assert exc.value.until == datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)


async def test_blocks_at_monthly_budget(db_session):
    for i in range(3):
        db_session.add(
            SerpApiRequest(
                params={"q": str(i)},
                params_hash=str(i),
                http_status=200,
                created_at=NOW,
            )
        )
    await db_session.commit()
    with pytest.raises(BudgetBlocked) as exc:
        await client(db_session, budget=3).search("q", None)
    assert "monthly budget" in exc.value.reason


async def test_blocks_at_per_job_cap(db_session):
    serp = client(db_session, cap=1)
    await serp.search("first", None)
    with pytest.raises(BudgetBlocked) as exc:
        await serp.search("second", None)
    assert exc.value.until is None  # stop searching, but the job isn't deferred


async def test_429_out_of_searches_defers_to_renewal(db_session):
    serp = client(
        db_session,
        search=(429, {"error": "out"}),
        account={**ACCOUNT, "total_searches_left": 0},
        reserve=-1,
    )
    with pytest.raises(BudgetBlocked) as exc:
        await serp.search("q", None)
    assert exc.value.until == datetime(2026, 11, 24, tzinfo=timezone.utc)


async def test_429_throughput_defers_to_next_hour(db_session):
    serp = client(db_session, search=(429, {"error": "slow down"}))
    with pytest.raises(BudgetBlocked) as exc:
        await serp.search("q", None)
    assert exc.value.until == datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)


async def test_401_pauses_all_serpapi_work(db_session):
    with pytest.raises(SerpApiPaused):
        await client(db_session, search=(401, {"error": "Invalid API key"})).search(
            "q", None
        )
    with pytest.raises(SerpApiPaused):
        await client(db_session).search("other", None)


async def test_400_skips_without_retry(db_session):
    calls: list[httpx.Request] = []
    assert (
        await client(
            db_session, search=(400, {"error": "Missing query"}), calls=calls
        ).search("q", None)
        is None
    )
    assert sum(1 for c in calls if c.url.path == "/search.json") == 1


async def test_server_errors_retry_twice_then_skip(db_session):
    calls: list[httpx.Request] = []
    assert (
        await client(db_session, search=(503, {}), calls=calls).search("q", None)
        is None
    )
    assert sum(1 for c in calls if c.url.path == "/search.json") == 3
