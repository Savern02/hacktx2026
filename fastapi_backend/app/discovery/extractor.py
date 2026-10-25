"""LLM extraction (spec Section 11), using Gemini function calling.

The model only proposes candidates; app.discovery.validator decides what's stored.
"""

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.discovery.models import CATEGORIES

log = logging.getLogger(__name__)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
TOOL_NAME = "record_programs"

_nullable_str = {"type": ["string", "null"]}

TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["page_publisher", "programs"],
    "properties": {
        "page_publisher": {
            "type": ["string", "null"],
            "description": "Organization that published the page, as named on the page",
        },
        "programs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "name",
                    "jurisdiction_level",
                    "jurisdiction_name",
                    "audience",
                    "categories",
                    "summary",
                    "is_active",
                    "evidence",
                    "confidence",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "jurisdiction_level": {
                        "enum": ["federal", "state", "county", "city"]
                    },
                    "jurisdiction_name": {"type": "string"},
                    "administering_agency": _nullable_str,
                    "related_federal_program": {
                        "type": ["string", "null"],
                        "description": "e.g. SNAP, when this is a state's version of a federal program",
                    },
                    "audience": {
                        "enum": ["individual", "business", "organization", "government"]
                    },
                    "categories": {
                        "type": "array",
                        "items": {"enum": list(CATEGORIES)},
                    },
                    "summary": {
                        "type": "string",
                        "description": "At most 400 characters, in your own words",
                    },
                    "eligibility_summary": _nullable_str,
                    "benefit_summary": _nullable_str,
                    "how_to_apply": _nullable_str,
                    "apply_url": _nullable_str,
                    "phone": _nullable_str,
                    "ends_on": {
                        "type": ["string", "null"],
                        "description": "YYYY-MM-DD, only if the page states an end date",
                    },
                    "is_active": {"enum": ["yes", "no", "unclear"]},
                    "evidence": {
                        "type": "object",
                        "required": ["name"],
                        "description": "Quotes of at most 200 characters, copied exactly from the page text",
                        "properties": {
                            "name": {"type": "string"},
                            "eligibility": _nullable_str,
                            "apply_url": _nullable_str,
                        },
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    },
}

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "extract_programs.md"


@dataclass(frozen=True)
class SystemPrompt:
    version: str
    template: str

    def render(self, page: "PageInput") -> str:
        values = {
            "jurisdiction_level": page.jurisdiction_level,
            "jurisdiction_display_name": page.jurisdiction_display_name,
            "state_name": page.state_name or "none",
            "page_url": page.url,
            "trust_tier": str(page.trust_tier),
        }
        out = self.template
        for key, value in values.items():
            out = out.replace("{" + key + "}", value)
        return out


@lru_cache
def load_system_prompt(path: Path = PROMPT_PATH) -> SystemPrompt:
    """prompts/extract_programs.md: a version header, then the Section 17.2 prompt verbatim."""
    raw = path.read_text()
    match = re.match(r"---\n(.*?)\n---\n", raw, re.S)
    if not match:
        raise ValueError(f"{path} is missing its version header")
    version = re.search(r"^version:\s*(\S+)", match.group(1), re.M)
    if not version:
        raise ValueError(f"{path} has no version")
    return SystemPrompt(version=version.group(1), template=raw[match.end() :].strip())


@dataclass
class PageInput:
    jurisdiction_level: str
    jurisdiction_display_name: str  # e.g. "Austin, TX"
    state_name: str | None
    url: str
    trust_tier: int
    text: str
    links: list[tuple[str, str]]


class Extractor(Protocol):
    prompt_version: str

    async def extract(self, page: PageInput) -> dict[str, Any]:
        ...


def build_user_message(page: PageInput, max_chars: int) -> str:
    """Section 17.2 user message: page text, then one link per line as 'anchor text | URL'."""
    links = "\n".join(f"{text} | {url}" for text, url in page.links[:300])
    return (
        f"<page_text>\n{page.text[:max_chars]}\n</page_text>\n"
        f"<page_links>\n{links}\n</page_links>"
    )


class GeminiExtractor:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_chars: int,
        http: httpx.AsyncClient | None = None,
    ):
        self._api_key = api_key
        self.model = model
        self.max_chars = max_chars
        self.http = http or httpx.AsyncClient(timeout=120)
        self.prompt = load_system_prompt()
        self.prompt_version = self.prompt.version

    async def extract(self, page: PageInput) -> dict[str, Any]:
        body = {
            "systemInstruction": {"parts": [{"text": self.prompt.render(page)}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": build_user_message(page, self.max_chars)}],
                }
            ],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": TOOL_NAME,
                            "description": "Record the assistance programs described on the page.",
                            "parametersJsonSchema": TOOL_SCHEMA,
                        }
                    ]
                }
            ],
            # Force the structured tool call; never parse free text.
            "toolConfig": {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": [TOOL_NAME],
                }
            },
            # Thinking off, deterministic output.
            "generationConfig": {
                "temperature": 0,
                "thinkingConfig": {"thinkingLevel": "minimal"},
            },
        }
        response = await self.http.post(
            GEMINI_URL.format(model=self.model),
            headers={"x-goog-api-key": self._api_key},
            json=body,
        )
        response.raise_for_status()
        for candidate in response.json().get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                call = part.get("functionCall")
                if call and call.get("name") == TOOL_NAME:
                    args = call.get("args") or {}
                    return args if isinstance(args, dict) else json.loads(args)
        log.warning("Gemini returned no %s call for %s", TOOL_NAME, page.url)
        return {"page_publisher": None, "programs": []}
