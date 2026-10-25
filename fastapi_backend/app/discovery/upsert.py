"""Merge validated candidates into programs (spec Section 9, step 7)."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Program, ProgramSource, SourceDocument
from app.discovery.normalize import normalize_name
from app.discovery.federal_programs import FEDERAL_ALIASES
from app.discovery.urls import canonicalize
from app.discovery.validator import ValidCandidate

SIMILARITY_THRESHOLD = 0.85
MERGE_FIELDS = (
    "administering_agency",
    "summary",
    "eligibility_summary",
    "benefit_summary",
    "how_to_apply",
    "apply_url",
    "phone",
    "ends_on",
)


async def find_match(
    session: AsyncSession, jurisdiction_id: int, normalized: str, apply_url: str | None
) -> Program | None:
    exact = await session.scalar(
        select(Program).where(
            Program.jurisdiction_id == jurisdiction_id,
            Program.normalized_name == normalized,
        )
    )
    if exact:
        return exact
    similar = await session.scalar(
        select(Program)
        .where(
            Program.jurisdiction_id == jurisdiction_id,
            func.similarity(Program.normalized_name, normalized)
            >= SIMILARITY_THRESHOLD,
        )
        .order_by(func.similarity(Program.normalized_name, normalized).desc())
        .limit(1)
    )
    if similar:
        return similar
    if apply_url:
        canonical = canonicalize(apply_url)
        for program in (
            await session.execute(
                select(Program).where(
                    Program.jurisdiction_id == jurisdiction_id,
                    Program.apply_url.is_not(None),
                )
            )
        ).scalars():
            if program.apply_url and canonicalize(program.apply_url) == canonical:
                return program
    return None


async def best_tier(session: AsyncSession, program_id: int) -> int:
    tier = await session.scalar(
        select(func.min(SourceDocument.trust_tier))
        .join(ProgramSource, ProgramSource.source_document_id == SourceDocument.id)
        .where(ProgramSource.program_id == program_id)
    )
    return tier or 4


def _parent_listing(related: str | None) -> str | None:
    return FEDERAL_ALIASES.get(normalize_name(related)) if related else None


async def upsert_program(
    session: AsyncSession,
    valid: ValidCandidate,
    source: SourceDocument,
    *,
    auto_publish_confidence: float,
    federal_parents: dict[str, int],
) -> str:
    """Returns 'inserted' or 'updated'."""
    c = valid.candidate
    normalized = normalize_name(c.name)
    publishable = (
        c.confidence >= auto_publish_confidence
        and source.trust_tier <= 2
        and not valid.force_review
    )
    listing = _parent_listing(c.related_federal_program)
    parent_id = federal_parents.get(listing) if listing else None
    new_values: dict[str, Any] = {
        "administering_agency": c.administering_agency,
        "summary": c.summary,
        "eligibility_summary": c.eligibility_summary,
        "benefit_summary": c.benefit_summary,
        "how_to_apply": c.how_to_apply,
        "apply_url": c.apply_url,
        "phone": c.phone,
        "ends_on": c.ends_on,
    }
    now = datetime.now(timezone.utc)

    program = await find_match(session, valid.jurisdiction_id, normalized, c.apply_url)
    if program is None:
        program = Program(
            jurisdiction_id=valid.jurisdiction_id,
            parent_program_id=parent_id,
            name=c.name,
            normalized_name=normalized,
            categories=list(c.categories),
            audience=c.audience,
            info_url=source.canonical_url,
            status=valid.status,
            review_status="published" if publishable else "needs_review",
            confidence=c.confidence,
            origin="discovery",
            last_verified_at=now,
            **new_values,
        )
        session.add(program)
        await session.flush()
        outcome = "inserted"
    else:
        better_source = source.trust_tier < await best_tier(session, program.id)
        for field in MERGE_FIELDS:
            value = new_values[field]
            if value is not None and (getattr(program, field) is None or better_source):
                setattr(program, field, value)
        program.categories = sorted(set(program.categories) | set(c.categories))
        program.parent_program_id = program.parent_program_id or parent_id
        program.last_verified_at = now
        if publishable and program.review_status == "needs_review":
            program.review_status = "published"
        if program.confidence is None or c.confidence > float(program.confidence):
            program.confidence = c.confidence
        outcome = "updated"

    stmt = insert(ProgramSource).values(
        program_id=program.id,
        source_document_id=source.id,
        evidence=c.evidence.model_dump(exclude_none=True),
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["program_id", "source_document_id"],
            set_={"evidence": stmt.excluded.evidence, "extracted_at": text("now()")},
        )
    )
    return outcome
