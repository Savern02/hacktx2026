"""Safe, polite page fetcher (spec Section 9, step 5; rules 6 and 7)."""

import asyncio
import hashlib
import io
import ipaddress
import logging
import re
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

log = logging.getLogger(__name__)

MAX_REDIRECTS = 5
TIMEOUT_S = 15
MAX_BYTES = 5 * 1024 * 1024
MIN_INTERVAL_S = 1.0
ROBOTS_TTL_S = 24 * 3600

Resolver = Callable[[str, int], Awaitable[list[str]]]


class FetchRefused(Exception):
    """The URL is not allowed (scheme, SSRF guard, robots.txt, type or size)."""


@dataclass
class FetchedPage:
    url: str  # final URL after redirects
    status: int
    content_type: str
    text: str
    links: list[tuple[str, str]] = field(
        default_factory=list
    )  # (anchor text, absolute URL)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    return list({info[4][0] for info in infos})


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def assert_public_url(url: str, resolve: Resolver) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchRefused(f"scheme not allowed: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise FetchRefused("no host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        # A literal IP is checked as-is; a name is resolved and every address checked.
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = await resolve(host, port)
        except OSError as exc:
            raise FetchRefused(f"DNS failed for {host}") from exc
    if not addresses or not all(_is_public(a) for a in addresses):
        raise FetchRefused(f"non-public address for {host}")


def extract_html(html: str, base_url: str) -> tuple[str, list[tuple[str, str]]]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, str(a["href"]))
        if href.startswith(("http://", "https://")):
            links.append((a.get_text(" ", strip=True), href))
    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "template",
            "svg",
            "nav",
            "footer",
            "header",
            "form",
        ]
    ):
        tag.decompose()
    root = soup.find("main") or soup.body or soup
    text = re.sub(r"\s+", " ", root.get_text(" ", strip=True)).strip()
    return text, links


def extract_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = [(page.extract_text() or "") for page in reader.pages[:50]]
    return re.sub(r"\s+", " ", " ".join(pages)).strip()


@dataclass
class _Hop:
    url: str
    status_code: int
    headers: httpx.Headers
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class SafeFetcher:
    def __init__(
        self,
        user_agent: str,
        *,
        resolve: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.user_agent = user_agent
        self.resolve = resolve
        self.sleep = sleep
        self.client = httpx.AsyncClient(
            transport=transport,
            timeout=TIMEOUT_S,
            follow_redirects=False,
            headers={"User-Agent": user_agent},
        )
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, tuple[float, robotparser.RobotFileParser | None]] = {}

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _throttle(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wait = MIN_INTERVAL_S - (time.monotonic() - last)
            if wait > 0:
                await self.sleep(wait)
        self._last_request[host] = time.monotonic()

    async def _get(self, url: str) -> _Hop:
        """One hop: SSRF check, per-host throttle, size-capped body."""
        await assert_public_url(url, self.resolve)
        await self._throttle(urlsplit(url).hostname or "")
        async with self.client.stream("GET", url) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise FetchRefused("response larger than 5 MB")
            return _Hop(
                str(response.url), response.status_code, response.headers, bytes(body)
            )

    async def _get_following(self, url: str) -> _Hop:
        for _ in range(MAX_REDIRECTS + 1):
            response = await self._get(url)
            if (
                response.status_code in (301, 302, 303, 307, 308)
                and "location" in response.headers
            ):
                url = urljoin(
                    url, response.headers["location"]
                )  # re-checked on the next hop
                continue
            return response
        raise FetchRefused("too many redirects")

    async def allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(origin)
        if cached is None or time.monotonic() - cached[0] > ROBOTS_TTL_S:
            parser: robotparser.RobotFileParser | None
            try:
                response = await self._get_following(f"{origin}/robots.txt")
                if response.status_code >= 500:
                    parser = None  # server error: assume disallowed, be polite
                else:
                    parser = robotparser.RobotFileParser()
                    parser.parse(
                        response.text.splitlines() if response.status_code < 400 else []
                    )
            except (httpx.HTTPError, FetchRefused):
                parser = None
            cached = (time.monotonic(), parser)
            self._robots[origin] = cached
        parser = cached[1]
        return parser is not None and parser.can_fetch(self.user_agent, url)

    async def fetch(self, url: str) -> FetchedPage:
        await assert_public_url(url, self.resolve)
        if not await self.allowed_by_robots(url):
            raise FetchRefused("disallowed by robots.txt")
        response = await self._get_following(url)
        final_url = response.url
        content_type = (
            response.headers.get("content-type", "").split(";")[0].strip().lower()
        )
        if response.status_code >= 400:
            return FetchedPage(final_url, response.status_code, content_type, "")
        if content_type in ("text/html", "application/xhtml+xml"):
            text, links = extract_html(response.text, final_url)
            return FetchedPage(
                final_url, response.status_code, content_type, text, links
            )
        if content_type == "application/pdf":
            return FetchedPage(
                final_url,
                response.status_code,
                content_type,
                extract_pdf(response.content),
            )
        raise FetchRefused(f"content type not allowed: {content_type or 'unknown'}")
