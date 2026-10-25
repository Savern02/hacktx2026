"""The one table spec for the Snowflake reporting copy (spec Section 16).

Snowflake columns are derived from the SQLAlchemy models, so Postgres and
Snowflake can't drift: add a column to a synced model and it syncs. All DDL,
column lists, stage loads and MERGE statements are generated from here.

Only the tables listed in SYNCED_TABLES ever leave Postgres. No user-level data
(users, user_locations, ZIP tables) is synced, by construction.
"""

from dataclasses import dataclass
from typing import Literal

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
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.discovery.models import (
    IngestionJob,
    Jurisdiction,
    JurisdictionCoverage,
    Program,
    ProgramSource,
    SerpApiRequest,
    SourceDocument,
)

Method = Literal["incremental", "append", "full"]
SYNCED_AT = "_SYNCED_AT"


@dataclass(frozen=True)
class SfColumn:
    pg_name: str
    sf_type: str

    @property
    def name(self) -> str:
        return self.pg_name.upper()  # unquoted identifiers: Snowflake stores upper case

    def from_stage(self, alias: str = "") -> str:
        """Stage columns are VARCHAR (array binds of strings); cast into the target type."""
        ref = f"{alias}{self.name}"
        if self.sf_type == "VARIANT":
            return f"PARSE_JSON({ref})"
        if self.sf_type == "ARRAY":
            return f"PARSE_JSON({ref})::ARRAY"
        if self.sf_type == "BOOLEAN":
            return f"TO_BOOLEAN({ref})"
        if self.sf_type == "DATE":
            return f"TO_DATE({ref})"
        if self.sf_type == "TIMESTAMP_TZ":
            return f"TO_TIMESTAMP_TZ({ref})"
        if self.sf_type == "FLOAT":
            return f"TO_DOUBLE({ref})"
        if self.sf_type.startswith("NUMBER"):
            return f"CAST({ref} AS {self.sf_type})"
        return ref


def snowflake_type(column_type: object) -> str:
    """Section 16 type mapping. Unknown types fail loudly instead of syncing badly."""
    if isinstance(column_type, (BigInteger, Integer, SmallInteger)):
        return "NUMBER(38,0)"
    if isinstance(column_type, Numeric):
        if column_type.precision is not None:
            return f"NUMBER({column_type.precision},{column_type.scale or 0})"
        return "FLOAT"
    if isinstance(column_type, ARRAY):
        return "ARRAY"
    if isinstance(column_type, JSONB):
        return "VARIANT"
    if isinstance(column_type, (Text, String)):
        return "VARCHAR"
    if isinstance(column_type, Boolean):
        return "BOOLEAN"
    if isinstance(column_type, DateTime):
        return "TIMESTAMP_TZ"
    if isinstance(column_type, Date):
        return "DATE"
    raise TypeError(f"No Snowflake mapping for {column_type!r}")


@dataclass(frozen=True)
class SyncedTable:
    pg_table: Table
    method: Method
    key: tuple[str, ...]
    exclude: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.pg_table.name.upper()

    @property
    def columns(self) -> list[SfColumn]:
        return [
            SfColumn(c.name, snowflake_type(c.type))
            for c in self.pg_table.columns
            if c.name not in self.exclude
        ]


SYNCED_TABLES: tuple[SyncedTable, ...] = (
    SyncedTable(Jurisdiction.__table__, "incremental", ("id",)),
    SyncedTable(Program.__table__, "incremental", ("id",)),
    SyncedTable(SourceDocument.__table__, "incremental", ("id",)),
    SyncedTable(ProgramSource.__table__, "full", ("program_id", "source_document_id")),
    SyncedTable(JurisdictionCoverage.__table__, "incremental", ("jurisdiction_id",)),
    SyncedTable(IngestionJob.__table__, "incremental", ("id",)),
    SyncedTable(SerpApiRequest.__table__, "append", ("id",), exclude=("raw_response",)),
)

# Never synced (Section 16). Checked by tests so a future edit can't add them.
NEVER_SYNCED = (
    "user",
    "users",
    "user_locations",
    "zip_county",
    "zcta_place",
    "financial_insights",
    "nessie_merchants",
)


@dataclass(frozen=True)
class Target:
    database: str
    schema: str = "RAW"

    def fq(self, table: str) -> str:
        return f"{self.database}.{self.schema}.{table}"


def create_table_sql(t: SyncedTable, target: Target, suffix: str = "") -> str:
    cols = ",\n  ".join(f"{c.name} {c.sf_type}" for c in t.columns)
    return f"CREATE TABLE IF NOT EXISTS {target.fq(t.name + suffix)} (\n  {cols},\n  {SYNCED_AT} TIMESTAMP_TZ\n)"


def create_stage_sql(t: SyncedTable, target: Target) -> str:
    cols = ",\n  ".join(f"{c.name} VARCHAR" for c in t.columns)
    return f"CREATE TRANSIENT TABLE IF NOT EXISTS {target.fq(t.name + '__STAGE')} (\n  {cols}\n)"


def stage_insert_sql(t: SyncedTable, target: Target) -> str:
    names = ", ".join(c.name for c in t.columns)
    marks = ", ".join("?" for _ in t.columns)
    return f"INSERT INTO {target.fq(t.name + '__STAGE')} ({names}) VALUES ({marks})"


def merge_sql(t: SyncedTable, target: Target) -> str:
    """Dedupe the stage, then MERGE. Incremental: newest updated_at wins; append: insert-only."""
    cols = t.columns
    key = [k.upper() for k in t.key]
    order = "UPDATED_AT DESC" if t.method == "incremental" else f"{key[0]} DESC"
    select = ",\n    ".join(f"{c.from_stage()} AS {c.name}" for c in cols)
    on = " AND ".join(f"t.{k} = s.{k}" for k in key)
    insert_cols = ", ".join([c.name for c in cols] + [SYNCED_AT])
    insert_vals = ", ".join([f"s.{c.name}" for c in cols] + ["CURRENT_TIMESTAMP()"])
    sql = (
        f"MERGE INTO {target.fq(t.name)} t\n"
        f"USING (\n  SELECT\n    {select}\n  FROM {target.fq(t.name + '__STAGE')}\n"
        f"  QUALIFY ROW_NUMBER() OVER (PARTITION BY {', '.join(key)} ORDER BY {order}) = 1\n) s\n"
        f"ON {on}\n"
    )
    if t.method == "incremental":
        updates = ",\n  ".join(
            f"t.{c.name} = s.{c.name}" for c in cols if c.name not in key
        )
        sql += (
            f"WHEN MATCHED AND s.UPDATED_AT >= t.UPDATED_AT THEN UPDATE SET\n  {updates},\n"
            f"  t.{SYNCED_AT} = CURRENT_TIMESTAMP()\n"
        )
    sql += f"WHEN NOT MATCHED THEN INSERT ({insert_cols})\n  VALUES ({insert_vals})"
    return sql


def full_reload_sql(t: SyncedTable, target: Target) -> list[str]:
    """Load the stage into <T>__NEXT, then atomically swap it in (Section 16, step 6)."""
    nxt = target.fq(t.name + "__NEXT")
    cols = ", ".join([c.name for c in t.columns] + [SYNCED_AT])
    select = ", ".join([c.from_stage() for c in t.columns] + ["CURRENT_TIMESTAMP()"])
    return [
        f"CREATE OR REPLACE TABLE {nxt} LIKE {target.fq(t.name)}",
        f"INSERT INTO {nxt} ({cols}) SELECT {select} FROM {target.fq(t.name + '__STAGE')}",
        f"ALTER TABLE {target.fq(t.name)} SWAP WITH {nxt}",
        f"DROP TABLE IF EXISTS {nxt}",
    ]


def all_ddl(target: Target) -> list[str]:
    statements = []
    for t in SYNCED_TABLES:
        statements += [create_table_sql(t, target), create_stage_sql(t, target)]
    return statements
