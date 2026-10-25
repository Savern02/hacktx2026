"""Shared helpers for the discovery CLI commands."""

import asyncio
import io
import logging
import zipfile
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, TypeVar

import httpx

from app.database import async_session_maker
from app.discovery.settings import discovery_settings

T = TypeVar("T")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


def run(main: Callable[[], Coroutine[Any, Any, T]]) -> T:
    return asyncio.run(main())


def download_bytes(url: str, cache_name: str, refresh: bool = False) -> bytes:
    """Download into DATA_DIR/census (cached unless refresh=True)."""
    cache_dir = discovery_settings.DATA_DIR / "census"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path: Path = cache_dir / cache_name
    if refresh or not path.exists():
        log = logging.getLogger("download")
        tmp = path.with_suffix(path.suffix + ".part")
        # Big public files can be slow: stream to disk, allow long stalls, retry.
        timeout = httpx.Timeout(30, read=180)
        for attempt in range(1, 4):
            log.info("Downloading %s (attempt %s)", url, attempt)
            try:
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        with tmp.open("wb") as f:
                            for chunk in response.iter_bytes():
                                f.write(chunk)
                tmp.replace(path)
                break
            except httpx.HTTPError as exc:
                log.warning("Download failed (%s)", type(exc).__name__)
                if attempt == 3:
                    if path.exists():
                        log.warning("Using the cached copy at %s", path)
                        break
                    raise
    return path.read_bytes()


def download_text(url: str, cache_name: str) -> str:
    """Download once into DATA_DIR/census and reuse; unzips single-file archives."""
    cache_dir = discovery_settings.DATA_DIR / "census"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path: Path = cache_dir / cache_name
    if not path.exists():
        logging.getLogger("download").info("Downloading %s", url)
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
        content = response.content
        if url.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                content = archive.read(archive.namelist()[0])
        path.write_bytes(content)
    return path.read_text(encoding="utf-8")


__all__ = [
    "async_session_maker",
    "discovery_settings",
    "download_bytes",
    "download_text",
    "run",
]
