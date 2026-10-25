"""The only module that talks to SerpApi (spec Section 10).

Every search: deterministic params, a 30-day replay from serpapi_requests, the
budget guard, error handling per the status table, and a log row without api_key.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import SerpApiRequest

log = logging.getLogger(__name__)

SEARCH_URL = "https://serpapi.com/search.json"
ACCOUNT_URL = "https://serpapi.com/account.json"
LOCATIONS_URL = "https://serpapi.com/locations.json"
ACCOUNT_CACHE_S = 60
REPLAY_WINDOW = timedelta(days=30)
RETRY_DELAYS_S = (10, 60)
THROUGHPUT_LIMIT = 0.9

# Process-wide pause after a 401/403: the key is bad, so stop all SerpApi work.
_global_pause: dict[str, str | None] = {"reason": None}


class SerpApiPaused(Exception):
    """401/403 from SerpApi: all SerpApi work is paused until an operator fixes the key."""


@dataclass
class BudgetBlocked(Exception):
    reason: str
    until: datetime | None  # None = per-job cap: stop searching but finish the job

    def __str__(self) -> str:
        return f"{self.reason} (until {self.until})"


@dataclass
class SearchResult:
    organic_results: list[dict[str, Any]]
    fully_empty: bool
    reused: bool


def params_hash(params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


def _next_hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def _period(account: dict[str, Any], now: datetime) -> tuple[datetime, datetime]:
    """Billing period (start, end). Ends at plan_renewal_date, else the calendar month."""
    renewal = account.get("plan_renewal_date")
    if renewal:
        end_date = date.fromisoformat(str(renewal)[:10])
        end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc)
        month = end.month - 1 or 12
        year = end.year - (1 if end.month == 1 else 0)
        start = end.replace(year=year, month=month, day=min(end.day, 28))
        return start, end
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end


class SerpApiClient:
    def __init__(
        self,
        session: AsyncSession,
        *,
        api_key: str,
        monthly_budget: int,
        reserve: int,
        per_job_cap: int,
        job_id: int | None = None,
        http: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.session = session
        self._api_key = api_key
        self.monthly_budget = monthly_budget
        self.reserve = reserve
        self.per_job_cap = per_job_cap
        self.job_id = job_id
        self.http = http or httpx.AsyncClient(timeout=30)
        self.sleep = sleep
        self.clock = clock
        self.searches_used = 0
        self._account: dict[str, Any] | None = None
        self._account_at = 0.0

    # --- Account API (free; doesn't count toward the quota) -------------------

    async def account(self, refresh: bool = False) -> dict[str, Any]:
        if (
            refresh
            or self._account is None
            or time.monotonic() - self._account_at > ACCOUNT_CACHE_S
        ):
            response = await self.http.get(
                ACCOUNT_URL, params={"api_key": self._api_key}
            )
            if response.status_code in (401, 403):
                self._pause(f"Account API returned {response.status_code}")
            response.raise_for_status()
            self._account = response.json()
            self._account_at = time.monotonic()
        assert self._account is not None
        return self._account

    async def check_budget(self) -> None:
        """Raise BudgetBlocked when the next search would break a limit (Section 10)."""
        if _global_pause["reason"]:
            raise SerpApiPaused(_global_pause["reason"])
        if self.searches_used >= self.per_job_cap:
            raise BudgetBlocked("per-job search cap reached", None)
        account = await self.account()
        now = self.clock()
        start, end = _period(account, now)
        if int(account.get("total_searches_left") or 0) <= self.reserve:
            raise BudgetBlocked("account at reserve", end)
        limit = int(account.get("account_rate_limit_per_hour") or 0)
        if (
            limit
            and int(account.get("this_hour_searches") or 0) >= THROUGHPUT_LIMIT * limit
        ):
            raise BudgetBlocked("hourly throughput at 90%", _next_hour(now))
        used = await self.session.scalar(
            select(func.count())
            .select_from(SerpApiRequest)
            .where(
                SerpApiRequest.created_at >= start, SerpApiRequest.http_status == 200
            )
        )
        if (used or 0) >= self.monthly_budget:
            raise BudgetBlocked("monthly budget reached", end)

    # --- Search -----------------------------------------------------------------

    @staticmethod
    def build_params(
        q: str, location: str | None, start: int | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "engine": "google",
            "q": q,
            "gl": "us",
            "hl": "en",
            "device": "desktop",
        }
        if location:
            params["location"] = location
        if start:
            params["start"] = start
        return params

    async def _replay(self, phash: str) -> dict[str, Any] | None:
        row = await self.session.scalar(
            select(SerpApiRequest.raw_response)
            .where(
                SerpApiRequest.params_hash == phash,
                SerpApiRequest.search_status == "Success",
                SerpApiRequest.raw_response.is_not(None),
                SerpApiRequest.created_at >= self.clock() - REPLAY_WINDOW,
            )
            .order_by(SerpApiRequest.created_at.desc())
            .limit(1)
        )
        return row

    def _pause(self, reason: str) -> None:
        _global_pause["reason"] = reason
        log.critical("ALERT: pausing all SerpApi work: %s", reason)
        raise SerpApiPaused(reason)

    async def _log(
        self, params: dict[str, Any], status: int | None, body: dict[str, Any] | None
    ) -> None:
        metadata = (body or {}).get("search_metadata") or {}
        organic = (body or {}).get("organic_results")
        self.session.add(
            SerpApiRequest(
                job_id=self.job_id,
                params=params,  # built without api_key, so nothing to strip
                params_hash=params_hash(params),
                serpapi_search_id=metadata.get("id"),
                http_status=status,
                search_status=metadata.get("status"),
                organic_count=len(organic) if isinstance(organic, list) else None,
                raw_response=body,
            )
        )
        await self.session.flush()

    async def search(
        self,
        q: str,
        location: str | None,
        *,
        start: int | None = None,
        allow_replay: bool = True,
    ) -> SearchResult | None:
        """Run one search. Returns None when the query is skipped (bad request, or
        SerpApi kept failing). Raises BudgetBlocked or SerpApiPaused."""
        params = self.build_params(q, location, start)
        phash = params_hash(params)
        if allow_replay and (stored := await self._replay(phash)) is not None:
            return self._result(stored, reused=True)

        await self.check_budget()
        for attempt in range(len(RETRY_DELAYS_S) + 1):
            try:
                response = await self.http.get(
                    SEARCH_URL, params={**params, "api_key": self._api_key}
                )
            except httpx.HTTPError as exc:
                log.warning("SerpApi transport error: %s", type(exc).__name__)
                status, body = None, None
            else:
                status = response.status_code
                try:
                    body = response.json()
                except ValueError:
                    body = None
            if status is not None:
                self.searches_used += 1 if status == 200 else 0

            if (
                status == 200
                and (body or {}).get("search_metadata", {}).get("status") == "Success"
            ):
                await self._log(params, status, body)
                return self._result(body or {}, reused=False)
            await self._log(params, status, body)

            if status == 400:
                log.error("SerpApi 400 for params %s; skipping query", params)
                return None
            if status in (401, 403):
                self._pause(f"SerpApi returned {status}")
            if status == 429:
                account = await self.account(refresh=True)
                now = self.clock()
                if int(account.get("total_searches_left") or 0) <= 0:
                    raise BudgetBlocked(
                        "out of searches (429)", _period(account, now)[1]
                    )
                raise BudgetBlocked("hourly throughput exceeded (429)", _next_hour(now))
            # 5xx, transport errors, or status "Error": retry twice, then skip.
            if attempt < len(RETRY_DELAYS_S):
                await self.sleep(RETRY_DELAYS_S[attempt])
        log.warning("SerpApi kept failing for %r; skipping query", q)
        return None

    @staticmethod
    def _result(body: dict[str, Any], *, reused: bool) -> SearchResult:
        info = body.get("search_information") or {}
        return SearchResult(
            organic_results=list(body.get("organic_results") or []),
            fully_empty=info.get("organic_results_state") == "Fully empty",
            reused=reused,
        )

    async def lookup_location(self, query: str) -> list[dict[str, Any]]:
        """SerpApi Locations API (free, no key)."""
        response = await self.http.get(LOCATIONS_URL, params={"q": query, "limit": 5})
        response.raise_for_status()
        return list(response.json())


def reset_global_pause() -> None:
    _global_pause["reason"] = None
