"""Run the Snowflake reporting sync once, or print its DDL (Section 16).

    python -m commands.snowflake_sync --print-ddl   # no connection; review the tables
    python -m commands.snowflake_sync               # one incremental run (needs SNOWFLAKE_*)
    python -m commands.snowflake_sync --full        # also force the PROGRAM_SOURCES reload

The worker runs this automatically every SNOWFLAKE_SYNC_INTERVAL_MINUTES when
SNOWFLAKE_ENABLED=true. Nothing in the app reads Snowflake.
"""

import argparse

from app.snowflake import client
from app.snowflake.sync import run_sync
from app.snowflake.tables import all_ddl
from commands._cli import async_session_maker, discovery_settings, run


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-ddl", action="store_true")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    target = client.target(discovery_settings)
    if args.print_ddl:
        print(";\n\n".join(all_ddl(target)) + ";")
        return
    if not discovery_settings.SNOWFLAKE_ENABLED:
        raise SystemExit(
            "SNOWFLAKE_ENABLED is false; set it to true (and the SNOWFLAKE_* settings) first."
        )
    print(
        await run_sync(
            async_session_maker,
            client.connector(discovery_settings),
            target,
            force_full=args.full,
        )
    )


if __name__ == "__main__":
    run(main)
