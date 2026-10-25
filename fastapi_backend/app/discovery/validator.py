"""Code-side validation of extracted candidates (spec Section 11).

Nothing reaches the database unless it passes every check here.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.discovery.models import CATEGORIES
from app.discovery.normalize import normalize_name, strip_place_suffix
from app.discovery.urls import canonicalize, registrable_domain

Category = Literal[
    "food", "housing", "utilities", "healthcare", "childcare", "cash_assistance",
    "employment", "education", "transportation", "seniors", "disability", "veterans",
    "tax_relief", "legal_aid", "disaster_relief", "internet", "small_business",
]  # fmt: skip
assert set(Category.__args__) == set(CATEGORIES)  # type: ignore[attr-defined]

Quote = Field(default=None, max_length=200)


class Evidence(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    eligibility: str | None = Quote
    apply_url: str | None = Quote


class Candidate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    jurisdiction_level: Literal["federal", "state", "county", "city"]
    jurisdiction_name: str = Field(min_length=1)
    administering_agency: str | None = None
    related_federal_program: str | None = None
    audience: Literal["individual", "business", "organization", "government"]
    categories: list[Category]
    summary: str = Field(max_length=400)
    eligibility_summary: str | None = None
    benefit_summary: str | None = None
    how_to_apply: str | None = None
    apply_url: str | None = None
    phone: str | None = None
    ends_on: date | None = None
    is_active: Literal["yes", "no", "unclear"]
    evidence: Evidence
    confidence: float = Field(ge=0, le=1)

    @field_validator("ends_on", mode="before")
    @classmethod
    def _blank_date(cls, v: Any) -> Any:
        return None if v in ("", None) else v


@dataclass
class JobScope:
    """The jurisdictions a job may file programs under."""

    level: str
    name: str  # Census legal name, e.g. "Austin city", "Texas"
    jurisdiction_id: int
    state_name: str | None = None
    state_id: int | None = None


@dataclass
class ValidCandidate:
    candidate: Candidate
    jurisdiction_id: int
    status: str  # active | inactive
    force_review: bool


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


_GOV_WORDS = re.compile(
    r"^(city|town|village|county|state|commonwealth|borough) of |"
    r" (city|town|village|county|parish|borough)$"
)


def _jurisdiction_key(name: str) -> str:
    s = normalize_name(strip_place_suffix(name))
    for _ in range(2):
        s = _GOV_WORDS.sub("", s).strip()
    return s


def _match_scope(c: Candidate, scope: JobScope) -> int | None:
    if c.jurisdiction_level == scope.level and _jurisdiction_key(
        c.jurisdiction_name
    ) == _jurisdiction_key(scope.name):
        return scope.jurisdiction_id
    if (
        c.jurisdiction_level == "state"
        and scope.state_name
        and scope.state_id
        and _jurisdiction_key(c.jurisdiction_name)
        == _jurisdiction_key(scope.state_name)
    ):
        return scope.state_id  # a state program found during a city job
    return None


def validate_candidates(
    raw: dict[str, Any],
    *,
    page_text: str,
    page_url: str,
    links: list[tuple[str, str]],
    scope: JobScope,
    rejected: dict[str, int],
) -> list[ValidCandidate]:
    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    haystack = _collapse(page_text)
    link_urls = {canonicalize(u) for _, u in links}
    link_haystack = _collapse(" ".join(f"{t} {u}" for t, u in links))
    page_domain = registrable_domain(page_url)
    valid: list[ValidCandidate] = []

    for item in raw.get("programs") or []:
        # 1. Schema, including the 400-character summary limit.
        try:
            c = Candidate.model_validate(item)
        except ValidationError:
            reject("schema")
            continue

        # 2. Every non-null evidence quote appears verbatim (whitespace/case-insensitive).
        quotes = {k: v for k, v in c.evidence.model_dump().items() if v}
        missing = [
            k
            for k, v in quotes.items()
            if _collapse(v) not in haystack
            and not (k == "apply_url" and _collapse(v) in link_haystack)
        ]
        if missing:
            reject("evidence_not_on_page")
            continue

        # 3. apply_url is absolute http(s), and in the link list or on the page's domain.
        if c.apply_url:
            if not re.match(r"^https?://", c.apply_url):
                reject("apply_url_not_absolute")
                continue
            if (
                canonicalize(c.apply_url) not in link_urls
                and registrable_domain(c.apply_url) != page_domain
            ):
                reject("apply_url_off_page")
                continue

        # 4. Jurisdiction: the job's own, or its parent state. Federal comes from SAM.gov.
        if c.jurisdiction_level == "federal":
            reject("federal")
            continue
        jurisdiction_id = _match_scope(c, scope)
        if jurisdiction_id is None:
            reject("wrong_jurisdiction")
            continue

        # 5. Activity. 6. Non-individual audiences are stored but hidden by the API.
        valid.append(
            ValidCandidate(
                candidate=c,
                jurisdiction_id=jurisdiction_id,
                status="inactive" if c.is_active == "no" else "active",
                force_review=c.is_active == "unclear",
            )
        )
    return valid
