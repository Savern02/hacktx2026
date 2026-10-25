import json
import re
from pathlib import Path

from app.discovery.extractor import PageInput, build_user_message, load_system_prompt
from app.discovery.fetcher import extract_html
from app.discovery.validator import JobScope, validate_candidates

FIXTURES = Path(__file__).parent / "fixtures"
SCOPE = JobScope(
    level="city", name="Austin city", jurisdiction_id=3, state_name="Texas", state_id=2
)


def page(name: str, url: str):
    text, links = extract_html((FIXTURES / f"{name}.html").read_text(), url)
    return text, links


def candidate(**overrides) -> dict:
    base = {
        "name": "Customer Assistance Program (CAP)",
        "jurisdiction_level": "city",
        "jurisdiction_name": "City of Austin",
        "audience": "individual",
        "categories": ["utilities"],
        "summary": "Utility bill discounts for income-qualified Austin households.",
        "apply_url": "https://www.austintexas.gov/cap/apply",
        "is_active": "yes",
        "evidence": {"name": "Customer Assistance Program (CAP)"},
        "confidence": 0.9,
    }
    return base | overrides


def run(programs: list[dict], name="austin_cap", url="https://www.austintexas.gov/cap"):
    text, links = page(name, url)
    rejected: dict[str, int] = {}
    valid = validate_candidates(
        {"programs": programs},
        page_text=text,
        page_url=url,
        links=links,
        scope=SCOPE,
        rejected=rejected,
    )
    return valid, rejected


def test_recorded_gemini_extraction_passes_validation():
    raw = json.loads((FIXTURES / "austin_cap.gemini.json").read_text())
    valid, rejected = run(raw["programs"])
    assert [v.candidate.name for v in valid] == ["Customer Assistance Program (CAP)"]
    assert valid[0].jurisdiction_id == SCOPE.jurisdiction_id and not rejected


def test_rejects_evidence_not_on_page():
    valid, rejected = run(
        [candidate(evidence={"name": "Austin Free Utilities Program"})]
    )
    assert not valid and rejected == {"evidence_not_on_page": 1}


def test_rejects_off_domain_apply_url_not_in_link_list():
    valid, rejected = run([candidate(apply_url="https://scam-site.example.com/apply")])
    assert not valid and rejected == {"apply_url_off_page": 1}


def test_drops_wrong_jurisdiction_and_federal():
    valid, rejected = run(
        [
            candidate(jurisdiction_name="Dallas"),
            candidate(jurisdiction_level="federal", jurisdiction_name="United States"),
        ]
    )
    assert not valid and rejected == {"wrong_jurisdiction": 1, "federal": 1}


def test_state_program_found_in_city_job_is_filed_under_the_state():
    valid, _ = run(
        [candidate(jurisdiction_level="state", jurisdiction_name="State of Texas")]
    )
    assert valid[0].jurisdiction_id == SCOPE.state_id


def test_schema_enforces_summary_limit_and_categories():
    valid, rejected = run(
        [candidate(summary="x" * 401), candidate(categories=["crypto"])]
    )
    assert not valid and rejected == {"schema": 2}


def test_activity_flags():
    valid, _ = run(
        [candidate(is_active="no"), candidate(name="CAP again", is_active="unclear")]
    )
    assert (valid[0].status, valid[0].force_review) == ("inactive", False)
    assert (valid[1].status, valid[1].force_review) == ("active", True)


def test_injected_instructions_produce_no_injected_program():
    # Real Gemini response recorded for a page that hides an injection payload.
    raw = json.loads((FIXTURES / "austin_injection.gemini.json").read_text())
    valid, _ = run(
        raw["programs"], "austin_injection", "https://www.austintexas.gov/rent-help"
    )
    names = [v.candidate.name.lower() for v in valid]
    assert not any("free money" in n for n in names)
    assert any("rental assistance" in n for n in names)


DOC = Path(__file__).parents[3] / "docs" / "program-discovery-pipeline.md"


def test_system_prompt_is_section_17_2_verbatim():
    doc = DOC.read_text()
    section = doc[doc.index("### 17.2 Extraction system prompt") :]
    expected = re.search(r"```text\n(.*?)\n```", section, re.S).group(1)
    prompt = load_system_prompt()
    assert prompt.template == expected.strip()
    assert prompt.version == "1"


def test_prompt_renders_context_and_user_message_follows_17_2():
    text, links = page("austin_injection", "https://www.austintexas.gov/rent-help")
    p = PageInput(
        "city",
        "Austin, TX",
        "Texas",
        "https://www.austintexas.gov/rent-help",
        1,
        text,
        links,
    )
    system = load_system_prompt().render(p)
    assert "Jurisdiction being researched: city - Austin, TX (state: Texas)" in system
    assert "Source trust tier: 1 " in system and "{" not in system
    message = build_user_message(p, 60000)
    assert message.startswith("<page_text>\n") and message.endswith("\n</page_links>")
    assert "\n</page_text>\n<page_links>\n" in message
    assert (
        "Apply for rental assistance | https://www.austintexas.gov/rent-help/apply"
        in message
    )
