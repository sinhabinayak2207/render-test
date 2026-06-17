"""Claude-powered Bid Scope keyword generator.

Runs ONCE per profile change: the user writes their scope in natural language,
Claude turns it into structured include/exclude + per-category keywords that the
DETERMINISTIC NLP filter then uses for free on every tender. Claude is never
called per tender here.
"""
from __future__ import annotations

import json
import logging

from .config import settings

log = logging.getLogger("keywords")

_SYSTEM = (
    "You build keyword sets for a deterministic government-tender scope filter. "
    "Given a company's description of the work it does, output the service lines and "
    "the keyword phrases (synonyms + Indian government-tender phrasing) that mark a tender "
    "as IN scope, plus phrases that mark a tender as OUT of scope (civil/construction, "
    "pure supply, manpower, housekeeping, etc.). Be comprehensive but precise — these are "
    "matched literally, so avoid generic words that cause false matches. Return ONLY JSON."
)


def _user(description: str) -> str:
    return (
        f"Company scope description:\n{description}\n\n"
        "Return ONLY this JSON:\n"
        "{\n"
        '  "service_lines": [string],\n'
        '  "scope_keywords": { "<service line>": [string, ...] },\n'
        '  "include_keywords": [string],\n'
        '  "exclude_keywords": [string]\n'
        "}"
    )


def generate_keywords(description: str) -> dict | None:
    """One Claude call → keyword sets. None if no key configured / on error."""
    if not settings.anthropic_api_key or not (description or "").strip():
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2500,
            temperature=0,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _user(description)}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        text = text[text.find("{"): text.rfind("}") + 1]  # strip any prose around JSON
        data = json.loads(text)
        return {
            "service_lines": data.get("service_lines") or [],
            "scope_keywords": data.get("scope_keywords") or {},
            "include_keywords": data.get("include_keywords") or [],
            "exclude_keywords": data.get("exclude_keywords") or [],
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("generate_keywords failed: %s", exc)
        return None
