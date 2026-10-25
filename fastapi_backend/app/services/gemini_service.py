"""Client for the Google Gemini generateContent REST API."""

import httpx

from app.config import settings
from app.schemas import ChatMessage

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(Exception):
    pass


async def generate_reply(system_prompt: str, messages: list[ChatMessage]) -> str:
    if not settings.GEMINI_KEY:
        raise GeminiError("GEMINI_KEY is not set")

    # Gemini expects the conversation to start with a user turn, so drop Equa's greeting.
    while messages and messages[0].role != "user":
        messages = messages[1:]
    if not messages:
        raise GeminiError("No user message to reply to")

    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [
            {
                "role": "user" if m.role == "user" else "model",
                "parts": [{"text": m.text}],
            }
            for m in messages
        ],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/models/{settings.GEMINI_MODEL}:generateContent",
                headers={"x-goog-api-key": settings.GEMINI_KEY},
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GeminiError("Gemini request failed") from exc

    candidates = response.json().get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    reply = "".join(p.get("text", "") for p in parts).strip()
    if not reply:
        raise GeminiError("Gemini returned no text")
    return reply
