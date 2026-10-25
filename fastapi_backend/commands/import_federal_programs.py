"""Import every current federal assistance program (no account or key needed).

    python -m commands.import_federal_programs

Source: GSA's public Assistance Listings extract on Data.gov (CC0). Downloads a fresh
copy (falling back to the cached one if the download fails), or use --file PATH.
Idempotent, so it's safe to re-run (weekly is plenty).
"""

import argparse
from pathlib import Path

from app.discovery import federal_programs
from commands._cli import async_session_maker, download_bytes, run


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, help="import a CSV you already downloaded")
    args = parser.parse_args()
    data = (
        args.file.read_bytes()
        if args.file
        else download_bytes(
            federal_programs.CSV_URL, "assistance_listings.csv", refresh=True
        )
    )
    async with async_session_maker() as session:
        result = await federal_programs.import_federal(
            session, federal_programs.decode_csv(data)
        )
    print(result)


if __name__ == "__main__":
    run(main)
