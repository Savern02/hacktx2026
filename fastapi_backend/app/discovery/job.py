"""Run one discovery or refresh job end to end (spec Section 9, steps 1-8)."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

import yaml
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery import urls
from app.discovery.extractor import Extractor, PageInput
from app.discovery.fetcher import FetchRefused, SafeFetcher
from app.discovery.models import (
    IngestionJob,
    Jurisdiction,
    JurisdictionCoverage,
    JurisdictionDomain,
    Program,
    SourceDocument,
)
from app.discovery.normalize import strip_place_suffix
from app.discovery.federal_programs import federal_parent_ids
from app.discovery.serpapi_client import BudgetBlocked, SerpApiClient
from app.discovery.settings import DiscoverySettings
from app.discovery.upsert import upsert_program
from app.discovery.validator import JobScope, validate_candidates

log = logging.getLogger(__name__)

REFRESH_AFTER = {
    "state": timedelta(days=120),
    "city": timedelta(days=180),
    "county": timedelta(days=180),
}
EMPTY_RETRY_AFTER = timedelta(days=90)
EMPTY_AGAIN_AFTER = timedelta(days=365)
MIN_TRUSTED_URLS = 5
KNOWN_DOMAIN_CONFIDENCE = 0.8


@dataclass
class JobDeps:
    serp: SerpApiClient
    fetcher: SafeFetcher
    extractor: Extractor
    settings: DiscoverySettings


@dataclass
class JobOutcome:
    deferred_until: datetime | None = None
    defer_reason: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)


@lru_cache
def load_templates(path: str) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def _placeholders(
    j: Jurisdiction, state: Jurisdiction | None, domain: str | None
) -> dict[str, str]:
    state_name = j.name if j.level == "state" else (state.name if state else "")
    return {
        "state_name": state_name,
        "state_code": j.state_code or "",
        "city_name": strip_place_suffix(j.name),
        "county_name": j.name,
        "domain": domain or "",
    }


async def _resolve_location(
    session: AsyncSession,
    serp: SerpApiClient,
    j: Jurisdiction,
    state: Jurisdiction | None,
) -> str | None:
    """Look up the SerpApi canonical location once and cache it on the jurisdiction."""
    if j.serpapi_location is not None:
        return j.serpapi_location or None
    wanted_state = j.name if j.level == "state" else (state.name if state else "")
    query = (
        wanted_state
        if j.level == "state"
        else f"{strip_place_suffix(j.name)}, {wanted_state}"
    )
    target = {"state": "State", "city": "City", "county": "County"}[j.level]
    canonical = ""
    try:
        for loc in await serp.lookup_location(query):
            name = str(loc.get("canonical_name", ""))
            if (
                loc.get("target_type") == target
                and wanted_state in name
                and name.endswith("United States")
            ):
                canonical = name
                break
    except Exception:
        log.warning("SerpApi location lookup failed for %s", j.display_name)
        return None
    j.serpapi_location = canonical  # "" caches "no good match": omit location next time
    await session.flush()
    return canonical or None


async def _record_domain(
    session: AsyncSession,
    jurisdiction: Jurisdiction,
    results: list[dict[str, Any]],
    fetcher: SafeFetcher,
) -> None:
    """Official domain discovery: a .gov result (0.9), or a site naming the jurisdiction (0.6)."""
    short = strip_place_suffix(jurisdiction.name).casefold()
    for result in results[:5]:
        link = result.get("link")
        if not link:
            continue
        domain = urls.registrable_domain(link)
        if urls.host_of(link).endswith(".gov"):
            confidence = 0.9
        else:
            try:
                home = await fetcher.fetch(f"https://{domain}/")
            except Exception:
                continue
            if short not in home.text[:5000].casefold():
                continue
            confidence = 0.6
        stmt = insert(JurisdictionDomain).values(
            jurisdiction_id=jurisdiction.id,
            domain=domain,
            added_by="discovery",
            confidence=confidence,
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["jurisdiction_id", "domain"],
                set_={
                    "confidence": func.greatest(
                        JurisdictionDomain.confidence, stmt.excluded.confidence
                    )
                },
            )
        )
        await session.flush()
        return


async def _domains(
    session: AsyncSession, jurisdiction_id: int
) -> list[tuple[str, float]]:
    rows = await session.execute(
        select(JurisdictionDomain.domain, JurisdictionDomain.confidence)
        .where(JurisdictionDomain.jurisdiction_id == jurisdiction_id)
        .order_by(JurisdictionDomain.confidence.desc())
    )
    return [(d, float(c)) for d, c in rows.all()]


async def _upsert_source(
    session: AsyncSession,
    url: str,
    tier: int,
    status: int | None,
    content_hash: str | None,
    failed: bool,
) -> SourceDocument:
    stmt = insert(SourceDocument).values(
        canonical_url=url,
        domain=urls.registrable_domain(url),
        trust_tier=tier,
        http_status=status,
        content_hash=content_hash,
        fetched_at=datetime.now(timezone.utc),
        consecutive_failures=1 if failed else 0,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["canonical_url"],
            set_={
                "trust_tier": func.least(
                    SourceDocument.trust_tier, stmt.excluded.trust_tier
                ),
                "http_status": stmt.excluded.http_status,
                "content_hash": func.coalesce(
                    stmt.excluded.content_hash, SourceDocument.content_hash
                ),
                "fetched_at": stmt.excluded.fetched_at,
                "consecutive_failures": SourceDocument.consecutive_failures + 1
                if failed
                else 0,
            },
        )
    )
    source = await session.scalar(
        select(SourceDocument)
        .where(SourceDocument.canonical_url == url)
        .execution_options(populate_existing=True)
    )
    assert source is not None
    return source


async def finalize_coverage(
    session: AsyncSession, jurisdiction: Jurisdiction, previous_status: str | None
) -> str:
    async def published(jid: int) -> int:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(Program)
                .where(
                    Program.jurisdiction_id == jid,
                    Program.review_status == "published",
                    Program.status == "active",
                    Program.audience == "individual",
                )
            )
            or 0
        )

    count = await published(jurisdiction.id)
    pending_review = int(
        await session.scalar(
            select(func.count())
            .select_from(Program)
            .where(
                Program.jurisdiction_id == jurisdiction.id,
                Program.review_status == "needs_review",
            )
        )
        or 0
    )
    now = datetime.now(timezone.utc)
    if count:
        status, refresh = "covered", now + REFRESH_AFTER[jurisdiction.level]
    elif pending_review:
        status, refresh = "awaiting_review", now + REFRESH_AFTER[jurisdiction.level]
    else:
        status = "covered_empty"
        refresh = now + (
            EMPTY_AGAIN_AFTER
            if previous_status == "covered_empty"
            else EMPTY_RETRY_AFTER
        )
    await session.execute(
        update(JurisdictionCoverage)
        .where(JurisdictionCoverage.jurisdiction_id == jurisdiction.id)
        .values(
            status=status,
            published_program_count=count,
            last_discovered_at=now,
            next_refresh_at=refresh,
            last_error=None,
        )
    )
    if jurisdiction.parent_id and jurisdiction.level != "state":
        # A city job can file programs under its state; keep that count current too.
        await session.execute(
            update(JurisdictionCoverage)
            .where(JurisdictionCoverage.jurisdiction_id == jurisdiction.parent_id)
            .values(published_program_count=await published(jurisdiction.parent_id))
        )
    return status


async def run_job(
    session: AsyncSession, job: IngestionJob, deps: JobDeps
) -> JobOutcome:
    s = deps.settings
    stats: dict[str, Any] = {
        "queries_run": 0,
        "replayed": 0,
        "urls_found": 0,
        "pages_fetched": 0,
        "pages_skipped_unchanged": 0,
        "fetch_refused": 0,
        "inserted": 0,
        "updated": 0,
        "rejected": {},
    }
    outcome = JobOutcome(stats=stats)

    # 1. Start.
    jurisdiction = await session.get(Jurisdiction, job.jurisdiction_id)
    assert jurisdiction is not None
    if jurisdiction.level == "federal":
        raise ValueError("federal programs come from SAM.gov, not discovery")
    state = (
        await session.get(Jurisdiction, jurisdiction.parent_id)
        if jurisdiction.parent_id and jurisdiction.level != "state"
        else None
    )
    coverage = await session.get(JurisdictionCoverage, jurisdiction.id)
    previous_status = coverage.status if coverage else None
    await session.execute(
        update(JurisdictionCoverage)
        .where(JurisdictionCoverage.jurisdiction_id == jurisdiction.id)
        .values(status="in_progress")
    )
    await session.commit()

    trusted = urls.trusted_domains()
    blocked = urls.blocked_domains()
    federal_parents = await federal_parent_ids(session)
    scope = JobScope(
        level=jurisdiction.level,
        name=jurisdiction.name,
        jurisdiction_id=jurisdiction.id,
        state_name=state.name if state else None,
        state_id=state.id if state else None,
    )

    # 2-3. Plan and run searches.
    section = load_templates(str(s.CONFIG_DIR / "query_templates.yaml"))[
        jurisdiction.level
    ]
    cap = min(
        int(section.get("max_searches", 99)),
        s.SERPAPI_MAX_SEARCHES_STATE_JOB
        if jurisdiction.level == "state"
        else s.SERPAPI_MAX_SEARCHES_CITY_JOB,
    )
    deps.serp.per_job_cap = cap
    deps.serp.job_id = job.id
    location = await _resolve_location(session, deps.serp, jurisdiction, state)

    candidates: dict[str, int] = {}  # canonical URL -> trust tier
    allow_replay = job.job_type != "refresh"
    blocked_until: BudgetBlocked | None = None

    for template in section["templates"]:
        domains = await _domains(session, jurisdiction.id)
        best_domain = domains[0][0] if domains else None
        if template["id"] == "domain" and (
            job.job_type == "refresh"
            or (domains and domains[0][1] >= KNOWN_DOMAIN_CONFIDENCE)
        ):
            continue
        if template.get("requires_domain") and not best_domain:
            continue
        query = template["q"].format(**_placeholders(jurisdiction, state, best_domain))
        try:
            pages = 0
            start: int | None = None
            while pages < 2:
                result = await deps.serp.search(
                    query, location, start=start, allow_replay=allow_replay
                )
                pages += 1
                if result is None:
                    break
                stats["replayed" if result.reused else "queries_run"] += 1
                if template["id"] == "domain":
                    await _record_domain(
                        session, jurisdiction, result.organic_results, deps.fetcher
                    )
                    break
                official = [d for d, _ in await _domains(session, jurisdiction.id)]
                new_good = 0
                for item in result.organic_results:
                    link = item.get("link")
                    if not link or not link.startswith(("http://", "https://")):
                        continue
                    url = urls.canonicalize(link)
                    if urls.is_blocked(url, blocked) or url in candidates:
                        continue
                    tier = urls.trust_tier(url, official, trusted)
                    candidates[url] = tier
                    new_good += tier <= 2
                # Second page only when page one paid off.
                if result.fully_empty or new_good < 3 or start:
                    break
                start = 10
        except BudgetBlocked as blocked_exc:
            blocked_until = blocked_exc
            break
        await session.commit()

    stats["urls_found"] = len(candidates)
    job.searches_used = deps.serp.searches_used
    if blocked_until is not None and blocked_until.until is not None:
        # Quota/throughput: defer the whole job; pages are cheap to re-find via replay.
        outcome.deferred_until, outcome.defer_reason = (
            blocked_until.until,
            blocked_until.reason,
        )
        await session.execute(
            update(JurisdictionCoverage)
            .where(JurisdictionCoverage.jurisdiction_id == jurisdiction.id)
            .values(status="queued")
        )
        await session.commit()
        return outcome

    # 4. Pick URLs: best tier first; tier 4 only when trusted sources are thin.
    trusted_count = sum(1 for t in candidates.values() if t <= 3)
    chosen = sorted(
        (
            u
            for u, t in candidates.items()
            if t <= 3 or trusted_count < MIN_TRUSTED_URLS
        ),
        key=lambda u: candidates[u],
    )[: s.MAX_PAGES_PER_JOB]

    # 5-7. Fetch, extract, validate, upsert.
    for url in chosen:
        tier = candidates[url]
        try:
            page = await deps.fetcher.fetch(url)
        except FetchRefused as exc:
            stats["fetch_refused"] += 1
            log.info("Not fetching %s: %s", url, exc)
            continue
        except Exception as exc:
            stats["fetch_refused"] += 1
            log.info("Fetch failed for %s: %s", url, type(exc).__name__)
            await _upsert_source(session, url, tier, None, None, failed=True)
            await session.commit()
            continue
        stats["pages_fetched"] += 1
        failed = page.status >= 400 or not page.text
        source = await _upsert_source(
            session,
            url,
            tier,
            page.status,
            None if failed else page.content_hash,
            failed,
        )
        if failed:
            await session.commit()
            continue
        if source.last_extracted_hash == page.content_hash:
            stats["pages_skipped_unchanged"] += 1
            continue
        raw = await deps.extractor.extract(
            PageInput(
                jurisdiction.level,
                jurisdiction.name,
                state.name if state else None,
                url,
                tier,
                page.text,
                page.links,
            )
        )
        valid = validate_candidates(
            raw,
            page_text=page.text,
            page_url=url,
            links=page.links,
            scope=scope,
            rejected=stats["rejected"],
        )
        for v in valid:
            outcome_kind = await upsert_program(
                session,
                v,
                source,
                auto_publish_confidence=s.AUTO_PUBLISH_CONFIDENCE,
                federal_parents=federal_parents,
            )
            stats[outcome_kind] += 1
        source.last_extracted_hash = page.content_hash
        await session.commit()

    # 8. Finish.
    stats["coverage"] = await finalize_coverage(session, jurisdiction, previous_status)
    await session.execute(
        update(IngestionJob)
        .where(IngestionJob.id == job.id)
        .values(
            status="succeeded",
            finished_at=datetime.now(timezone.utc),
            searches_used=deps.serp.searches_used,
            stats=stats,
            last_error=None,
            locked_by=None,
        )
    )
    await session.commit()
    return outcome
