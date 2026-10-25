"""Load ZIP reference data: zcta_place (Census) and zip_county (HUD, or Census fallback).

    python -m commands.load_zip_data            # HUD if HUD_API_TOKEN is set, else Census
    python -m commands.load_zip_data --source census

Re-run quarterly. Each table is replaced in one transaction.
"""

import argparse
import logging

from app.discovery import zip_data
from commands._cli import async_session_maker, discovery_settings, download_text, run

log = logging.getLogger("load_zip_data")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["hud", "census"], default=None)
    args = parser.parse_args()
    source = args.source or ("hud" if discovery_settings.HUD_API_TOKEN else "census")

    async with async_session_maker() as session:
        zcta = download_text(zip_data.ZCTA_PLACE_URL, "tab20_zcta520_place20_natl.txt")
        print(f"zcta_place: {await zip_data.load_zcta_place(session, zcta)} rows")

        if source == "hud":
            discovery_settings.require("HUD_API_TOKEN")
            assert discovery_settings.HUD_API_TOKEN
            payload = await zip_data.fetch_hud_zip_county(
                discovery_settings.HUD_API_TOKEN
            )
            count = await zip_data.load_zip_county(session, payload)
        else:
            log.warning(
                "Using the Census ZCTA-county file for zip_county (no HUD_API_TOKEN). "
                "Ratios are land-area based and PO-box ZIPs won't resolve by city name."
            )
            data = download_text(
                zip_data.ZCTA_COUNTY_URL, "tab20_zcta520_county20_natl.txt"
            )
            count = await zip_data.load_zip_county_census(session, data)
        print(f"zip_county ({source}): {count} rows")


if __name__ == "__main__":
    run(main)
