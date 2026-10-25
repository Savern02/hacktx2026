"""Real Snowflake connection: a TYPE = SERVICE user with key-pair (JWT) auth, never a password."""

from collections.abc import Sequence

from app.discovery.settings import DiscoverySettings
from app.snowflake.tables import Target


class ConnectorConnection:
    """Adapts snowflake-connector-python to the sync's small connection protocol."""

    def __init__(self, raw):  # type: ignore[no-untyped-def]
        self._raw = raw

    def execute(self, sql: str) -> None:
        with self._raw.cursor() as cur:
            cur.execute(sql)

    def executemany(self, sql: str, rows: Sequence[Sequence[str | None]]) -> None:
        if rows:
            with self._raw.cursor() as cur:
                cur.executemany(sql, rows)  # qmark paramstyle -> array binds

    def close(self) -> None:
        self._raw.close()


def target(settings: DiscoverySettings) -> Target:
    return Target(database=settings.SNOWFLAKE_DATABASE)


def connector(settings: DiscoverySettings):  # type: ignore[no-untyped-def]
    settings.require(
        "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_PATH"
    )

    def connect() -> ConnectorConnection:
        import snowflake.connector  # imported lazily: only the sync needs it

        raw = snowflake.connector.connect(
            account=settings.SNOWFLAKE_ACCOUNT,
            user=settings.SNOWFLAKE_USER,
            authenticator="SNOWFLAKE_JWT",
            private_key_file=str(settings.SNOWFLAKE_PRIVATE_KEY_PATH),
            private_key_file_pwd=settings.SNOWFLAKE_PRIVATE_KEY_PASSPHRASE or None,
            role=settings.SNOWFLAKE_ROLE,
            warehouse=settings.SNOWFLAKE_WAREHOUSE,
            database=settings.SNOWFLAKE_DATABASE,
            schema="RAW",
            paramstyle="qmark",
            application="Equa-ProgramPipeline",
        )
        return ConnectorConnection(raw)

    return connect
