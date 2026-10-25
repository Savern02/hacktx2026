import httpx
import pytest

from app.discovery.fetcher import FetchRefused, SafeFetcher, assert_public_url
from app.discovery.urls import canonicalize, is_blocked, registrable_domain, trust_tier

PUBLIC_IP = "93.184.216.34"


def resolver(table: dict[str, str]):
    async def resolve(host: str, port: int) -> list[str]:
        return [table.get(host, PUBLIC_IP)]

    return resolve


async def _no_sleep(_):
    return None


def fetcher(handler, table=None) -> SafeFetcher:
    return SafeFetcher(
        "EquaBot/1.0 (+https://example.com/bot)",
        resolve=resolver(table or {}),
        transport=httpx.MockTransport(handler),
        sleep=_no_sleep,
    )


def test_canonicalize():
    assert (
        canonicalize("HTTPS://WWW.AustinTexas.gov/CAP/?utm_source=x&id=2#apply")
        == "https://www.austintexas.gov/CAP?id=2"
    )
    assert canonicalize("https://example.gov/") == "https://example.gov"


def test_trust_tiers_and_blocklist():
    official = ["austintexas.gov"]
    trusted = ["211texas.org"]
    assert trust_tier("https://www.austintexas.gov/cap", official, trusted) == 1
    assert trust_tier("https://hhs.texas.gov/snap", official, trusted) == 2
    assert trust_tier("https://www.va.mil/x", official, trusted) == 2
    assert trust_tier("https://www.211texas.org/help", official, trusted) == 3
    assert trust_tier("https://randomblog.com/help", official, trusted) == 4
    assert is_blocked("https://www.facebook.com/cityofaustin", ["facebook.com"])
    assert not is_blocked("https://notfacebook.com/", ["facebook.com"])
    assert registrable_domain("https://www.austintexas.gov/x") == "austintexas.gov"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://10.1.2.3/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.gov/",
    ],
)
async def test_ssrf_guard_rejects_private_targets(url):
    with pytest.raises(FetchRefused):
        await assert_public_url(url, resolver({}))


async def test_ssrf_guard_rejects_names_resolving_to_private_addresses():
    with pytest.raises(FetchRefused):
        await assert_public_url(
            "https://sneaky.example.com/", resolver({"sneaky.example.com": "10.0.0.5"})
        )


async def test_redirect_to_private_address_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            302, headers={"location": "http://internal.example.com/secrets"}
        )

    f = fetcher(handler, {"internal.example.com": "192.168.1.10"})
    with pytest.raises(FetchRefused):
        await f.fetch("https://www.austintexas.gov/cap")


async def test_robots_disallow_is_honored():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(
            200, html="<main>ok</main>", headers={"content-type": "text/html"}
        )

    f = fetcher(handler)
    with pytest.raises(FetchRefused, match="robots"):
        await f.fetch("https://www.austintexas.gov/private/page")
    page = await f.fetch("https://www.austintexas.gov/public/page")
    assert page.text == "ok"
    assert "/private/page" not in seen
    assert seen.count("/robots.txt") == 1  # cached


async def test_fetch_extracts_main_text_links_and_sends_user_agent():
    agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers["user-agent"])
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        html = '<nav>Menu</nav><main><h1>CAP</h1><p>Lower bills.</p><a href="/cap/apply">Apply</a></main><script>x()</script>'
        return httpx.Response(
            200, html=html, headers={"content-type": "text/html; charset=utf-8"}
        )

    page = await fetcher(handler).fetch("https://www.austintexas.gov/cap")
    assert page.text == "CAP Lower bills. Apply"
    assert page.links == [("Apply", "https://www.austintexas.gov/cap/apply")]
    assert all(a.startswith("EquaBot/1.0") for a in agents)


async def test_non_html_or_pdf_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200, content=b"\x00", headers={"content-type": "image/png"}
        )

    with pytest.raises(FetchRefused, match="content type"):
        await fetcher(handler).fetch("https://www.austintexas.gov/logo.png")
