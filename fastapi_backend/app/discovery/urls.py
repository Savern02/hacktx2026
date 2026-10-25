"""URL canonicalization, registrable domains, and trust tiers (spec Section 9, step 4)."""

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import tldextract
import yaml

from app.discovery.settings import discovery_settings

# Bundled public-suffix snapshot only: never download the list at runtime.
_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def canonicalize(url: str) -> str:
    """Lowercase scheme and host, drop the fragment, utm_* params and a trailing slash."""
    parts = urlsplit(url.strip())
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")
        ]
    )
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def registrable_domain(url_or_host: str) -> str:
    host = host_of(url_or_host) if "://" in url_or_host else url_or_host.lower()
    ext = _extract(host)
    return ext.top_domain_under_public_suffix or host


def _on_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def trust_tier(
    url: str, official_domains: Iterable[str], trusted_domains: Iterable[str]
) -> int:
    host = host_of(url)
    if any(_on_domain(host, d) for d in official_domains):
        return 1
    if host.endswith(".gov") or host.endswith(".mil"):
        return 2
    if any(_on_domain(host, d) for d in trusted_domains):
        return 3
    return 4


@lru_cache
def _domain_list(path: Path) -> frozenset[str]:
    if not path.exists():
        return frozenset()
    data = yaml.safe_load(path.read_text()) or {}
    return frozenset(d.lower() for d in data.get("domains", []))


def blocked_domains() -> frozenset[str]:
    return _domain_list(discovery_settings.CONFIG_DIR / "blocked_domains.yaml")


def trusted_domains() -> frozenset[str]:
    return _domain_list(discovery_settings.CONFIG_DIR / "trusted_domains.yaml")


def is_blocked(url: str, blocked: Iterable[str]) -> bool:
    host = host_of(url)
    return any(_on_domain(host, d) for d in blocked)
