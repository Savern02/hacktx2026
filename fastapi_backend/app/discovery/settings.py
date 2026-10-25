"""Settings for the program discovery pipeline (spec Section 13).

Kept separate from app.config.Settings so the web API boots without pipeline
keys. Commands that need a key call `require(...)`, which fails fast with a
clear message instead of failing halfway through a job.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class DiscoverySettings(BaseSettings):
    SERPAPI_API_KEY: str | None = None
    SERPAPI_MONTHLY_BUDGET: int | None = None
    SERPAPI_RESERVE: int = 50
    SERPAPI_MAX_SEARCHES_STATE_JOB: int = 20
    SERPAPI_MAX_SEARCHES_CITY_JOB: int = 12

    HUD_API_TOKEN: str | None = None

    # Extraction uses Gemini (sponsor AI) instead of Claude; see the spec's Deviations.
    GEMINI_KEY: str | None = None
    EXTRACTION_MODEL: str = "gemini-3.5-flash"
    EXTRACTION_MAX_CHARS: int = 60000

    AUTO_PUBLISH_CONFIDENCE: float = 0.80
    MAX_PAGES_PER_JOB: int = 40
    WORKER_CONCURRENCY: int = 2
    FETCH_USER_AGENT: str | None = None
    ENABLE_COUNTY_DISCOVERY: bool = False
    BOOTSTRAP_CITIES_TOP_N: int = 0

    ALLOW_LIVE_SMOKE: bool = False

    # Snowflake reporting copy (Section 16). Off by default; nothing reads from it.
    SNOWFLAKE_ENABLED: bool = False
    SNOWFLAKE_ACCOUNT: str | None = None  # account identifier, e.g. "myorg-myaccount"
    SNOWFLAKE_USER: str = "PROGRAM_PIPELINE_SVC"
    SNOWFLAKE_PRIVATE_KEY_PATH: Path | None = None  # PEM file; keep it out of the repo
    SNOWFLAKE_PRIVATE_KEY_PASSPHRASE: str | None = None
    SNOWFLAKE_ROLE: str = "PROGRAM_PIPELINE_LOADER"
    SNOWFLAKE_WAREHOUSE: str = "PROGRAM_PIPELINE_WH"
    SNOWFLAKE_DATABASE: str = "PROGRAM_PIPELINE"
    SNOWFLAKE_SYNC_INTERVAL_MINUTES: int = 60

    # Downloaded reference files (Census) are cached here; gitignored.
    DATA_DIR: Path = BACKEND_DIR / "data"
    CONFIG_DIR: Path = BACKEND_DIR / "config"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    def require(self, *names: str) -> None:
        missing = [n for n in names if getattr(self, n) in (None, "")]
        if missing:
            raise SystemExit(
                "Missing required setting(s): "
                + ", ".join(missing)
                + ". Add them to fastapi_backend/.env (see .env.example)."
            )


discovery_settings = DiscoverySettings()
