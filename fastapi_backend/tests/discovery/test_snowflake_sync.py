"""Snowflake reporting sync (spec Section 16). A fake connection records SQL; no live calls."""

import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.discovery.models import Program, SerpApiRequest, SnowflakeSyncState
from app.discovery.settings import DiscoverySettings
from app.discovery.worker import snowflake_hook
from app.snowflake import tables as spec
from app.snowflake.sync import LOCK_KEY, check_staleness, run_sync, to_stage_value

TARGET = spec.Target("PROGRAM_PIPELINE")


class FakeSnowflake:
    def __init__(self, fail_on: str | None = None):
        self.statements: list[str] = []
        self.batches: list[tuple[str, list]] = []
        self.fail_on = fail_on
        self.closed = False

    def execute(self, sql: str) -> None:
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("boom")
        self.statements.append(sql)

    def executemany(self, sql: str, rows) -> None:
        self.batches.append((sql, list(rows)))

    def close(self) -> None:
        self.closed = True

    def rows_into(self, table: str) -> int:
        return sum(
            len(rows) for sql, rows in self.batches if f".{table}__STAGE " in sql
        )


def test_type_mapping():
    from sqlalchemy import (
        ARRAY,
        BigInteger,
        Boolean,
        Date,
        DateTime,
        Integer,
        Numeric,
        SmallInteger,
        String,
        Text,
    )
    from sqlalchemy.dialects.postgresql import JSONB

    cases = {
        BigInteger(): "NUMBER(38,0)",
        Integer(): "NUMBER(38,0)",
        SmallInteger(): "NUMBER(38,0)",
        Numeric(3, 2): "NUMBER(3,2)",
        Numeric(): "FLOAT",
        Text(): "VARCHAR",
        String(5): "VARCHAR",
        Boolean(): "BOOLEAN",
        Date(): "DATE",
        DateTime(timezone=True): "TIMESTAMP_TZ",
        JSONB(): "VARIANT",
        ARRAY(Text): "ARRAY",
    }
    for pg_type, expected in cases.items():
        assert spec.snowflake_type(pg_type) == expected


def test_no_user_level_data_is_ever_synced():
    names = {t.pg_table.name for t in spec.SYNCED_TABLES}
    assert not names & set(spec.NEVER_SYNCED)
    columns = {c.pg_name for t in spec.SYNCED_TABLES for c in t.columns}
    assert not columns & {"user_id", "zip", "email", "hashed_password", "raw_response"}


def test_ddl_and_merge_come_from_one_spec():
    programs = next(t for t in spec.SYNCED_TABLES if t.name == "PROGRAMS")
    ddl = spec.create_table_sql(programs, TARGET)
    assert ddl.startswith("CREATE TABLE IF NOT EXISTS PROGRAM_PIPELINE.RAW.PROGRAMS (")
    assert (
        "CONFIDENCE NUMBER(3,2)" in ddl
        and "CATEGORIES ARRAY" in ddl
        and "_SYNCED_AT TIMESTAMP_TZ" in ddl
    )
    merge = spec.merge_sql(programs, TARGET)
    assert (
        "QUALIFY ROW_NUMBER() OVER (PARTITION BY ID ORDER BY UPDATED_AT DESC) = 1"
        in merge
    )
    assert "WHEN MATCHED AND s.UPDATED_AT >= t.UPDATED_AT THEN UPDATE SET" in merge
    # Every spec column appears in the stage insert and in the MERGE insert list.
    for col in programs.columns:
        assert col.name in spec.stage_insert_sql(programs, TARGET)
        assert re.search(rf"\b{col.name}\b", merge.split("WHEN NOT MATCHED")[1])
    serp = next(t for t in spec.SYNCED_TABLES if t.name == "SERPAPI_REQUESTS")
    assert "WHEN MATCHED" not in spec.merge_sql(serp, TARGET)  # append-only


def test_stage_values_are_strings():
    assert to_stage_value(True) == "true"
    assert to_stage_value({"a": 1}) == '{"a": 1}'
    assert to_stage_value(["food"]) == '["food"]'
    assert (
        to_stage_value(datetime(2026, 10, 24, 12, tzinfo=timezone.utc))
        == "2026-10-24T12:00:00+00:00"
    )
    assert to_stage_value(None) is None


async def _seed(db_session, geo, n_programs: int = 3) -> None:
    for i in range(n_programs):
        db_session.add(
            Program(
                jurisdiction_id=geo.austin.id,
                name=f"P{i}",
                normalized_name=f"p{i}",
                audience="individual",
                origin="discovery",
            )
        )
    db_session.add(
        SerpApiRequest(
            params={"q": "x"},
            params_hash="h",
            http_status=200,
            raw_response={"secret": "do not sync"},
        )
    )
    await db_session.commit()


async def test_first_run_loads_everything_and_sets_watermarks(
    db_session, geo, sessions
):
    await _seed(db_session, geo)
    fake = FakeSnowflake()
    result = await run_sync(sessions, lambda: fake, TARGET)

    assert result["PROGRAMS"] == 3 and result["SERPAPI_REQUESTS"] == 1
    assert fake.rows_into("PROGRAMS") == 3
    assert any(
        s.startswith("MERGE INTO PROGRAM_PIPELINE.RAW.PROGRAMS ")
        for s in fake.statements
    )
    assert any(
        "SWAP WITH PROGRAM_PIPELINE.RAW.PROGRAM_SOURCES__NEXT" in s
        for s in fake.statements
    )
    # raw_response never leaves Postgres.
    serp_sql, serp_rows = next(
        b for b in fake.batches if ".SERPAPI_REQUESTS__STAGE " in b[0]
    )
    assert "RAW_RESPONSE" not in serp_sql and "do not sync" not in str(serp_rows)
    state = await db_session.get(SnowflakeSyncState, "programs", populate_existing=True)
    assert (
        state.watermark_ts is not None
        and state.rows_last_run == 3
        and state.last_error is None
    )
    serp_state = await db_session.get(
        SnowflakeSyncState, "serpapi_requests", populate_existing=True
    )
    assert serp_state.watermark_id >= 1
    assert fake.closed


async def test_next_run_reads_only_rows_after_watermark_minus_overlap(
    db_session, geo, sessions
):
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.add(
        Program(
            jurisdiction_id=geo.austin.id,
            name="Old",
            normalized_name="old",
            audience="individual",
            origin="discovery",
            updated_at=old,
        )
    )
    await db_session.commit()
    await run_sync(sessions, FakeSnowflake, TARGET)
    # Pretend the last run was an hour ago: 'Old' (2h) is outside the 10-minute overlap.
    await db_session.execute(
        text(
            "UPDATE snowflake_sync_state SET watermark_ts = now() - interval '1 hour' WHERE table_name = 'programs'"
        )
    )
    db_session.add(
        Program(
            jurisdiction_id=geo.austin.id,
            name="New",
            normalized_name="new",
            audience="individual",
            origin="discovery",
        )
    )
    await db_session.commit()

    fake = FakeSnowflake()
    await run_sync(sessions, lambda: fake, TARGET)
    loaded = [
        row for sql, rows in fake.batches if ".PROGRAMS__STAGE " in sql for row in rows
    ]
    names = {row[3] for row in loaded}  # NAME is the 4th spec column
    assert names == {"New"}


async def test_failed_table_keeps_watermark_and_others_still_sync(
    db_session, geo, sessions
):
    await _seed(db_session, geo)
    fake = FakeSnowflake(fail_on="MERGE INTO PROGRAM_PIPELINE.RAW.PROGRAMS ")
    result = await run_sync(sessions, lambda: fake, TARGET)
    assert result["PROGRAMS"] == "failed"
    assert result["JURISDICTIONS"] > 0  # other tables unaffected
    state = await db_session.get(SnowflakeSyncState, "programs", populate_existing=True)
    assert state.watermark_ts is None and "boom" in state.last_error


async def test_full_reload_is_nightly_unless_forced(db_session, geo, sessions):
    await run_sync(sessions, FakeSnowflake, TARGET)
    again = FakeSnowflake()
    result = await run_sync(sessions, lambda: again, TARGET)
    assert result["PROGRAM_SOURCES"] == "not due"
    assert not any("SWAP WITH" in s for s in again.statements)
    forced = FakeSnowflake()
    await run_sync(sessions, lambda: forced, TARGET, force_full=True)
    assert any("SWAP WITH" in s for s in forced.statements)


async def test_concurrent_run_is_skipped_by_advisory_lock(engine, sessions, geo):
    async with engine.connect() as other:
        assert await other.scalar(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}
        )
        fake = FakeSnowflake()
        assert await run_sync(sessions, lambda: fake, TARGET) == {"skipped": "locked"}
        assert not fake.statements
        await other.scalar(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})


async def test_staleness_alert(db_session, caplog):
    now = datetime.now(timezone.utc)
    db_session.add(
        SnowflakeSyncState(
            table_name="programs", last_success_at=now - timedelta(hours=4)
        )
    )
    db_session.add(
        SnowflakeSyncState(
            table_name="jurisdictions", last_success_at=now - timedelta(minutes=30)
        )
    )
    await db_session.commit()
    stale = await check_staleness(db_session, timedelta(hours=1), now=now)
    assert stale == ["PROGRAMS"]
    assert "ALERT" in caplog.text


def test_disabled_means_no_sync_hook(sessions):
    assert snowflake_hook(DiscoverySettings(SNOWFLAKE_ENABLED=False), sessions) is None
    with pytest.raises(SystemExit):  # enabled without credentials fails fast
        snowflake_hook(
            DiscoverySettings(SNOWFLAKE_ENABLED=True, SNOWFLAKE_ACCOUNT=None), sessions
        )
