"""One-way Postgres -> Snowflake reporting sync (spec Section 16).

Nothing in the app reads Snowflake. A failed run only records last_error and
keeps the old watermark; signup and discovery never notice.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.discovery.models import SnowflakeSyncState
from app.snowflake import tables as spec

log = logging.getLogger(__name__)

BATCH_SIZE = 10_000
OVERLAP = timedelta(minutes=10)
LOCK_KEY = 7_316_504_216  # arbitrary, constant: one sync run at a time across workers
STALE_AFTER_INTERVALS = 3


class SnowflakeConnection(Protocol):
    """The slice of a DB-API connection the sync uses (qmark paramstyle)."""

    def execute(self, sql: str) -> None:
        ...

    def executemany(self, sql: str, rows: Sequence[Sequence[str | None]]) -> None:
        ...

    def close(self) -> None:
        ...


def to_stage_value(value: Any) -> str | None:
    """Every stage column is VARCHAR; the MERGE casts back to the target type."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _rows_for(t: spec.SyncedTable, records: Sequence[Any]) -> list[list[str | None]]:
    return [[to_stage_value(r._mapping[c.pg_name]) for c in t.columns] for r in records]


async def _sf(conn: SnowflakeConnection, sql: str) -> None:
    await asyncio.to_thread(conn.execute, sql)


async def _load_batch(
    conn: SnowflakeConnection,
    t: spec.SyncedTable,
    target: spec.Target,
    rows: list[list[str | None]],
) -> None:
    await _sf(conn, f"TRUNCATE TABLE IF EXISTS {target.fq(t.name + '__STAGE')}")
    await asyncio.to_thread(conn.executemany, spec.stage_insert_sql(t, target), rows)


async def _state(session: AsyncSession, table_name: str) -> SnowflakeSyncState:
    state = await session.get(SnowflakeSyncState, table_name)
    if state is None:
        state = SnowflakeSyncState(table_name=table_name)
        session.add(state)
        await session.flush()
    return state


async def _sync_incremental(
    session: AsyncSession,
    conn: SnowflakeConnection,
    t: spec.SyncedTable,
    target: spec.Target,
    state: SnowflakeSyncState,
) -> int:
    table = t.pg_table
    key = table.c[t.key[0]]
    cols = [table.c[c.pg_name] for c in t.columns]
    loaded = 0
    cursor: tuple[datetime, Any] | None = None
    since = state.watermark_ts - OVERLAP if state.watermark_ts else None
    while True:
        stmt = select(*cols).order_by(table.c.updated_at, key).limit(BATCH_SIZE)
        if since is not None:
            stmt = stmt.where(table.c.updated_at > since)
        if cursor is not None:  # keyset pagination: no offsets, no skipped ties
            stmt = stmt.where(tuple_(table.c.updated_at, key) > tuple_(*cursor))
        records = (await session.execute(stmt)).all()
        if not records:
            break
        await _load_batch(conn, t, target, _rows_for(t, records))
        await _sf(conn, spec.merge_sql(t, target))
        await _sf(conn, f"TRUNCATE TABLE {target.fq(t.name + '__STAGE')}")
        last = records[-1]._mapping
        cursor = (last["updated_at"], last[t.key[0]])
        # Advance only after the MERGE succeeded.
        state.watermark_ts = max(
            state.watermark_ts or last["updated_at"], last["updated_at"]
        )
        loaded += len(records)
        await session.commit()
        if len(records) < BATCH_SIZE:
            break
    return loaded


async def _sync_append(
    session: AsyncSession,
    conn: SnowflakeConnection,
    t: spec.SyncedTable,
    target: spec.Target,
    state: SnowflakeSyncState,
) -> int:
    table = t.pg_table
    key = table.c[t.key[0]]
    cols = [table.c[c.pg_name] for c in t.columns]  # excluded columns never selected
    loaded = 0
    while True:
        records = (
            await session.execute(
                select(*cols)
                .where(key > (state.watermark_id or 0))
                .order_by(key)
                .limit(BATCH_SIZE)
            )
        ).all()
        if not records:
            break
        await _load_batch(conn, t, target, _rows_for(t, records))
        await _sf(conn, spec.merge_sql(t, target))
        await _sf(conn, f"TRUNCATE TABLE {target.fq(t.name + '__STAGE')}")
        state.watermark_id = int(records[-1]._mapping[t.key[0]])
        loaded += len(records)
        await session.commit()
        if len(records) < BATCH_SIZE:
            break
    return loaded


async def _sync_full(
    session: AsyncSession,
    conn: SnowflakeConnection,
    t: spec.SyncedTable,
    target: spec.Target,
) -> int:
    table = t.pg_table
    cols = [table.c[c.pg_name] for c in t.columns]
    order = [table.c[k] for k in t.key]
    await _sf(conn, f"TRUNCATE TABLE IF EXISTS {target.fq(t.name + '__STAGE')}")
    loaded = 0
    offset = 0
    while True:
        records = (
            await session.execute(
                select(*cols).order_by(*order).limit(BATCH_SIZE).offset(offset)
            )
        ).all()
        if not records:
            break
        await asyncio.to_thread(
            conn.executemany, spec.stage_insert_sql(t, target), _rows_for(t, records)
        )
        loaded += len(records)
        offset += len(records)
        if len(records) < BATCH_SIZE:
            break
    for sql in spec.full_reload_sql(t, target):
        await _sf(conn, sql)
    await _sf(conn, f"TRUNCATE TABLE {target.fq(t.name + '__STAGE')}")
    return loaded


def full_reload_due(state: SnowflakeSyncState, now: datetime) -> bool:
    """Nightly: once per UTC day."""
    return state.last_success_at is None or state.last_success_at.date() < now.date()


async def run_sync(
    sessions: async_sessionmaker[AsyncSession],
    connect: Callable[[], SnowflakeConnection],
    target: spec.Target,
    *,
    force_full: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, Any]:
    """One sync run. Returns per-table results; never raises for a table failure."""
    engine = sessions.kw["bind"]
    # Advisory locks belong to a connection; hold one for the whole run.
    async with engine.connect() as lock_conn:
        got = await lock_conn.scalar(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}
        )
        if not got:
            log.info("Snowflake sync already running elsewhere; skipping")
            return {"skipped": "locked"}
        try:
            return await _run_locked(sessions, connect, target, force_full, clock)
        finally:
            await lock_conn.scalar(
                text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY}
            )


async def _run_locked(sessions, connect, target, force_full, clock) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    results: dict[str, Any] = {}
    conn = await asyncio.to_thread(connect)
    try:
        for sql in spec.all_ddl(target):
            await _sf(conn, sql)
        async with sessions() as session:
            for t in spec.SYNCED_TABLES:
                state = await _state(session, t.pg_table.name)
                await session.commit()
                now = clock()
                if t.method == "full" and not (
                    force_full or full_reload_due(state, now)
                ):
                    results[t.name] = "not due"
                    continue
                try:
                    if t.method == "incremental":
                        rows = await _sync_incremental(session, conn, t, target, state)
                    elif t.method == "append":
                        rows = await _sync_append(session, conn, t, target, state)
                    else:
                        rows = await _sync_full(session, conn, t, target)
                except Exception as exc:
                    await session.rollback()
                    state = await _state(session, t.pg_table.name)
                    state.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                    await session.commit()
                    log.warning(
                        "Snowflake sync failed for %s: %s", t.name, type(exc).__name__
                    )
                    results[t.name] = "failed"
                    continue
                state.rows_last_run = rows
                state.last_success_at = now
                state.last_error = None
                await session.commit()
                results[t.name] = rows
    finally:
        await asyncio.to_thread(conn.close)
    return results


async def check_staleness(
    session: AsyncSession, interval: timedelta, now: datetime | None = None
) -> list[str]:
    """Tables whose last success is older than three intervals. Logs an ALERT for each."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - interval * STALE_AFTER_INTERVALS
    stale = []
    for t in spec.SYNCED_TABLES:
        if t.method == "full":
            continue  # nightly by design
        state = await session.get(SnowflakeSyncState, t.pg_table.name)
        if (
            state is not None
            and state.last_success_at is not None
            and state.last_success_at < cutoff
        ):
            stale.append(t.name)
    if stale:
        log.critical(
            "ALERT: Snowflake sync stale for %s (no success in %s)",
            stale,
            interval * STALE_AFTER_INTERVALS,
        )
    return stale
