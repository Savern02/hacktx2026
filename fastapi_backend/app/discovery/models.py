"""Program discovery tables (docs/program-discovery-pipeline.md, Section 5).

Constraints and partial indexes mirror the spec exactly: the dedupe logic
(one open job per jurisdiction, one federal row, assistance-listing uniqueness)
depends on them.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

JURISDICTION_LEVELS = ("federal", "state", "county", "city")
AUDIENCES = ("individual", "business", "organization", "government")
COVERAGE_STATUSES = (
    "none",
    "queued",
    "in_progress",
    "covered",
    "covered_empty",
    "awaiting_review",
    "failed",
    "not_applicable",
)
CATEGORIES = (
    "food",
    "housing",
    "utilities",
    "healthcare",
    "childcare",
    "cash_assistance",
    "employment",
    "education",
    "transportation",
    "seniors",
    "disability",
    "veterans",
    "tax_relief",
    "legal_aid",
    "disaster_relief",
    "internet",
    "small_business",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Jurisdiction(Base):
    __tablename__ = "jurisdictions"
    __table_args__ = (
        CheckConstraint(_in("level", JURISDICTION_LEVELS), name="jurisdictions_level"),
        UniqueConstraint("level", "geoid", name="jurisdictions_level_geoid"),
        Index(
            "jurisdictions_one_federal",
            "level",
            unique=True,
            postgresql_where=text("level = 'federal'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    level: Mapped[str] = mapped_column(Text)
    geoid: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(String(2))
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("jurisdictions.id")
    )
    place_class: Mapped[str | None] = mapped_column(Text)
    is_incorporated: Mapped[bool | None] = mapped_column(Boolean)
    serpapi_location: Mapped[str | None] = mapped_column(Text)


class JurisdictionDomain(Base):
    __tablename__ = "jurisdiction_domains"
    __table_args__ = (
        PrimaryKeyConstraint("jurisdiction_id", "domain"),
        CheckConstraint(
            _in("added_by", ("discovery", "manual")),
            name="jurisdiction_domains_added_by",
        ),
    )

    jurisdiction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jurisdictions.id", ondelete="CASCADE")
    )
    domain: Mapped[str] = mapped_column(Text)
    added_by: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2))


class ZipCounty(Base):
    __tablename__ = "zip_county"
    __table_args__ = (PrimaryKeyConstraint("zip", "county_geoid"),)

    zip: Mapped[str] = mapped_column(String(5))
    county_geoid: Mapped[str] = mapped_column(String(5))
    usps_city: Mapped[str | None] = mapped_column(Text)
    usps_state: Mapped[str | None] = mapped_column(String(2))
    res_ratio: Mapped[Decimal] = mapped_column(Numeric)
    tot_ratio: Mapped[Decimal] = mapped_column(Numeric)
    data_year: Mapped[int] = mapped_column(SmallInteger)
    data_quarter: Mapped[int] = mapped_column(SmallInteger)


class ZctaPlace(Base):
    __tablename__ = "zcta_place"
    __table_args__ = (PrimaryKeyConstraint("zcta", "place_geoid"),)

    zcta: Mapped[str] = mapped_column(String(5))
    place_geoid: Mapped[str] = mapped_column(String(7))
    land_part_m2: Mapped[int] = mapped_column(BigInteger)
    zcta_land_m2: Mapped[int] = mapped_column(BigInteger)


class UserLocation(Base):
    __tablename__ = "user_locations"
    __table_args__ = (
        CheckConstraint(
            _in(
                "method", ("zcta_place", "usps_city_name", "county_only", "unresolved")
            ),
            name="user_locations_method",
        ),
    )

    # users.id is a UUID in this repo (fastapi-users), so this is too.
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    zip: Mapped[str] = mapped_column(String(5))
    state_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("jurisdictions.id")
    )
    county_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("jurisdictions.id")
    )
    city_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("jurisdictions.id")
    )
    method: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    alternates: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    user_confirmed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Program(Base):
    __tablename__ = "programs"
    __table_args__ = (
        CheckConstraint(_in("audience", AUDIENCES), name="programs_audience"),
        CheckConstraint(
            "categories <@ ARRAY["
            + ", ".join(repr(c) for c in CATEGORIES)
            + "]::text[]",
            name="programs_categories",
        ),
        CheckConstraint(
            _in("status", ("active", "inactive", "unknown")), name="programs_status"
        ),
        CheckConstraint(
            _in("review_status", ("published", "needs_review", "rejected")),
            name="programs_review_status",
        ),
        CheckConstraint(
            _in("origin", ("seed_sam_gov", "seed_manual", "discovery", "admin")),
            name="programs_origin",
        ),
        UniqueConstraint(
            "jurisdiction_id", "normalized_name", name="programs_jurisdiction_name"
        ),
        Index(
            "programs_name_trgm",
            "normalized_name",
            postgresql_using="gin",
            postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ),
        Index(
            "programs_visible",
            "jurisdiction_id",
            postgresql_where=text("review_status = 'published' AND status = 'active'"),
        ),
        Index(
            "programs_assistance_listing",
            "jurisdiction_id",
            text("(external_ids->>'assistance_listing_id')"),
            unique=True,
            postgresql_where=text("external_ids->>'assistance_listing_id' IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jurisdictions.id")
    )
    parent_program_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("programs.id")
    )
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(Text)
    administering_agency: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'")
    )
    audience: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    eligibility_summary: Mapped[str | None] = mapped_column(Text)
    benefit_summary: Mapped[str | None] = mapped_column(Text)
    how_to_apply: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)
    info_url: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    ends_on: Mapped[date | None] = mapped_column(Date)
    external_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    review_status: Mapped[str] = mapped_column(
        Text, server_default=text("'needs_review'")
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    origin: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SourceDocument(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        CheckConstraint("trust_tier BETWEEN 1 AND 4", name="source_documents_tier"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    domain: Mapped[str] = mapped_column(Text)
    trust_tier: Mapped[int] = mapped_column(SmallInteger)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    content_hash: Mapped[str | None] = mapped_column(Text)
    last_extracted_hash: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(
        SmallInteger, server_default=text("0")
    )


class ProgramSource(Base):
    __tablename__ = "program_sources"
    __table_args__ = (PrimaryKeyConstraint("program_id", "source_document_id"),)

    program_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("programs.id", ondelete="CASCADE")
    )
    source_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_documents.id", ondelete="CASCADE")
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JurisdictionCoverage(Base):
    __tablename__ = "jurisdiction_coverage"
    __table_args__ = (
        CheckConstraint(
            _in("status", COVERAGE_STATUSES), name="jurisdiction_coverage_status"
        ),
    )

    jurisdiction_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("jurisdictions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(Text)
    published_program_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0")
    )
    user_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            _in("job_type", ("discover", "refresh")), name="ingestion_jobs_type"
        ),
        CheckConstraint(
            _in("status", ("pending", "running", "succeeded", "dead", "cancelled")),
            name="ingestion_jobs_status",
        ),
        CheckConstraint(
            _in("triggered_by", ("signup", "bootstrap", "schedule", "admin")),
            name="ingestion_jobs_triggered_by",
        ),
        Index(
            "ingestion_jobs_one_open",
            "jurisdiction_id",
            "job_type",
            unique=True,
            postgresql_where=text("status IN ('pending','running')"),
        ),
        Index(
            "ingestion_jobs_claimable",
            "priority",
            "run_after",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jurisdictions.id")
    )
    job_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    triggered_by: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, server_default=text("100"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, server_default=text("5"))
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_count: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    searches_used: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SerpApiRequest(Base):
    __tablename__ = "serpapi_requests"
    __table_args__ = (
        Index("serpapi_requests_created", "created_at"),
        Index("serpapi_requests_params", "params_hash", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ingestion_jobs.id")
    )
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)  # never includes api_key
    params_hash: Mapped[str] = mapped_column(Text)
    serpapi_search_id: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    search_status: Mapped[str | None] = mapped_column(Text)
    organic_count: Mapped[int | None] = mapped_column(SmallInteger)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
