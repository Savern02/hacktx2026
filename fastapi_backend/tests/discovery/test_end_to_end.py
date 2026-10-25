"""A fixture-driven discovery job takes Austin from queued to covered (spec Section 14)."""

import json
from pathlib import Path

import httpx
from sqlalchemy import select, update

from app.discovery.extractor import PageInput
from app.discovery.fetcher import SafeFetcher
from app.discovery.job import JobDeps
from app.discovery.models import (
    IngestionJob,
    JurisdictionCoverage,
    JurisdictionDomain,
    Program,
    ProgramSource,
    SourceDocument,
)
from app.discovery.serpapi_client import SerpApiClient
from app.discovery.settings import DiscoverySettings
from app.discovery.worker import run_forever

FIXTURES = Path(__file__).parent / "fixtures"
ACCOUNT = {
    "total_searches_left": 1000,
    "this_hour_searches": 0,
    "account_rate_limit_per_hour": 1000,
    "plan_renewal_date": "2099-01-01",
}
PAGES = {
    "/cap": "austin_cap.html",
    "/rent-help": "austin_injection.html",
}


def serp_handler(calls: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/account.json":
            return httpx.Response(200, json=ACCOUNT)
        if request.url.path == "/locations.json":
            return httpx.Response(
                200,
                json=[
                    {
                        "canonical_name": "Austin,Texas,United States",
                        "target_type": "City",
                    }
                ],
            )
        q = request.url.params["q"]
        calls.append(q)
        links = (
            [{"link": "https://www.austintexas.gov/"}]
            if "official website" in q
            else [
                {"link": "https://www.austintexas.gov/cap?utm_source=google"},
                {"link": "https://www.austintexas.gov/rent-help"},
                {"link": "https://www.facebook.com/austintexasgov"},
            ]
        )
        return httpx.Response(
            200,
            json={
                "search_metadata": {"id": q, "status": "Success"},
                "organic_results": links,
            },
        )

    return handler


def site_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /\n")
    name = PAGES.get(request.url.path)
    if name is None:
        return httpx.Response(
            404, html="<main>Not found</main>", headers={"content-type": "text/html"}
        )
    return httpx.Response(
        200, text=(FIXTURES / name).read_text(), headers={"content-type": "text/html"}
    )


class RecordedExtractor:
    """Replays Gemini responses recorded for the fixture pages."""

    prompt_version = "1"

    async def extract(self, page: PageInput):
        name = "austin_cap" if page.url.endswith("/cap") else "austin_injection"
        return json.loads((FIXTURES / f"{name}.gemini.json").read_text())


async def _public(host, port):
    return ["93.184.216.34"]


async def _no_sleep(_):
    return None


async def test_discovery_job_takes_a_city_from_queued_to_covered(
    db_session, geo, sessions
):
    db_session.add(
        IngestionJob(
            jurisdiction_id=geo.austin.id,
            job_type="discover",
            triggered_by="signup",
            priority=10,
        )
    )
    await db_session.execute(
        update(JurisdictionCoverage)
        .where(JurisdictionCoverage.jurisdiction_id == geo.austin.id)
        .values(status="queued")
    )
    await db_session.commit()

    settings = DiscoverySettings(
        SERPAPI_MAX_SEARCHES_CITY_JOB=4,
        MAX_PAGES_PER_JOB=10,
        AUTO_PUBLISH_CONFIDENCE=0.8,
    )
    queries: list[str] = []
    serp_http = httpx.AsyncClient(transport=httpx.MockTransport(serp_handler(queries)))
    fetcher = SafeFetcher(
        "EquaBot/1.0 (+https://example.com/bot)",
        resolve=_public,
        transport=httpx.MockTransport(site_handler),
        sleep=_no_sleep,
    )

    def make_deps(session):
        serp = SerpApiClient(
            session,
            api_key="k",
            monthly_budget=100,
            reserve=0,
            per_job_cap=4,
            http=serp_http,
            sleep=_no_sleep,
        )
        return JobDeps(
            serp=serp, fetcher=fetcher, extractor=RecordedExtractor(), settings=settings
        )

    await run_forever(sessions, make_deps, once=True)

    job = await db_session.scalar(
        select(IngestionJob).execution_options(populate_existing=True)
    )
    assert job.status == "succeeded", job.last_error
    assert job.stats["prompt_version"] == "1"
    assert job.searches_used <= 4 and len(queries) <= 4  # never over the per-job cap
    assert queries[0].startswith("Austin TX city government official website")

    coverage = await db_session.get(
        JurisdictionCoverage, geo.austin.id, populate_existing=True
    )
    assert coverage.status == "covered" and coverage.published_program_count >= 1
    assert coverage.next_refresh_at is not None

    domain = await db_session.scalar(
        select(JurisdictionDomain).where(
            JurisdictionDomain.jurisdiction_id == geo.austin.id
        )
    )
    assert (domain.domain, float(domain.confidence)) == ("austintexas.gov", 0.9)

    published = (
        (
            await db_session.execute(
                select(Program).where(Program.review_status == "published")
            )
        )
        .scalars()
        .all()
    )
    assert published and not any("free money" in p.name.lower() for p in published)
    for program in published:
        links = (
            await db_session.execute(
                select(ProgramSource, SourceDocument)
                .join(SourceDocument)
                .where(ProgramSource.program_id == program.id)
            )
        ).all()
        assert links, f"{program.name} has no source"
        for link, doc in links:
            assert doc.trust_tier == 1 and doc.content_hash and link.evidence["name"]
    # The blocked domain was never fetched or stored.
    assert not await db_session.scalar(
        select(SourceDocument).where(SourceDocument.domain == "facebook.com")
    )
