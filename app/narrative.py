"""Claude narrative (Step 4) — the report prose. One call per tender, adapts to
verdict. CS Direkt is the BIDDER. Crisp, no marketing adjectives. Returns only
the narrative columns; gracefully no-op if ANTHROPIC_API_KEY is unset.
"""
from __future__ import annotations

import json
import logging

from .config import settings

log = logging.getLogger("narrative")

_SYSTEM = (
    "You are the CS Direkt bid-review analyst. CS Direkt is the BIDDER, not the issuing "
    "authority. Write crisp, declarative prose — no marketing adjectives (robust, "
    "world-class, comprehensive). You phrase decisions that were ALREADY made by rules; "
    "do not re-judge eligibility. Where the tender fits, cite CS Direkt's matching past "
    "projects (cs_direkt_track_record) BY NAME in narrative_fit / strategic_fit_basis. "
    "If client_analysis_instructions or client_auto_reject_risks is present, HONOUR them — the "
    "client's stated preferences, risk factors and rejection guidance — when phrasing the "
    "recommendation, key insight and risk; flag rejection-worthy risks clearly. Return ONLY JSON."
)


def generate_narrative(row: dict, profile=None) -> dict:
    if not settings.anthropic_api_key:
        return {}
    verdict = (row.get("verdict") or "PENDING").upper()
    track = []
    if profile is not None and getattr(profile, "portfolio", None):
        from .portfolio import relevant_projects
        track = [
            {"project": p.get("project_name"), "value_cr": p.get("approx_value_cr"), "client": p.get("client")}
            for p in relevant_projects(profile.portfolio, row.get("matched_categories"), top_n=4)
        ]
    meta = {
        "title": row.get("title"),
        "verdict": verdict,
        "score": row.get("competitiveness_score"),
        "scope_summary": row.get("scope_summary"),
        "matched_categories": row.get("matched_categories"),
        "estimated_value_cr": (row.get("estimated_value") or 0) / 1e7 if row.get("estimated_value") else None,
        "emd": row.get("emd_amount"),
        "risk_level": row.get("risk_level"),
        "cs_direkt_track_record": track,
        "client_analysis_instructions": (getattr(profile, "analysis_instructions", "") if profile else "") or "",
        "client_auto_reject_risks": (getattr(profile, "auto_reject_risks", "") if profile else "") or "",
        "eligibility_conditions": (row.get("eligibility_conditions") or [])[:8],
        "reasons_rejected": row.get("reasons_rejected"),
        "gaps_to_address": row.get("gaps_to_address"),
    }
    if verdict in ("ELIGIBLE", "PARTIAL"):
        keys = (
            '{\n'
            '  "narrative_fit": string (<=90 words, why bid),\n'
            '  "key_business_insight": string (<=30 words; ELIGIBLE → prefix "PREMIUM FIT: "),\n'
            '  "strategic_fit_basis": string (<=18 words),\n'
            '  "compliance_basis": string (<=40 words, name certs/licenses),\n'
            '  "risk_layperson_explanation": string (2-4 plain sentences),\n'
            '  "pre_bid_queries": [{"sr_no": number, "page_ref": string, "clause_description": string, "question": string, "rationale": string}]\n'
            '}'
        )
    else:  # INELIGIBLE / EXCLUDED
        keys = (
            '{\n'
            '  "key_business_insight": string (<=30 words, prefix "CRITICAL DROP: "),\n'
            '  "disqualification_triggers": [{"name": string, "evidence": string}],\n'
            '  "business_logic_explanation": string (3-4 plain sentences)\n'
            '}'
        )
    user = "Tender:\n" + json.dumps(meta, ensure_ascii=False, default=str) + "\n\nReturn ONLY this JSON:\n" + keys
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1500,
            temperature=0.2,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        text = text[text.find("{"): text.rfind("}") + 1]
        data = json.loads(text)
        return {k: v for k, v in data.items() if v not in (None, "", [], {})}
    except Exception as exc:  # noqa: BLE001
        log.warning("generate_narrative failed: %s", exc)
        return {}
