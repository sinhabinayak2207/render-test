"""Hybrid extractor: Python/regex first (free), gpt-4o-mini ONLY for what's left.

Returns (fields, log). `log` records what Python filled vs missed and what the
LLM filled — stored in tenders.extraction_log so the regex can be improved later.
"""
from __future__ import annotations

import json
import logging

from .config import settings
from .extract_py import python_fields

log = logging.getLogger("llm_extract")

# Regex CAN do these — only send to the LLM if regex missed them.
_REGEXABLE = [
    "min_turnover_cr", "min_networth_cr", "pbg_percent", "estimated_value_cr",
    "pre_bid_date", "opening_date", "project_duration", "authority_contact", "award_method",
]
# Semantic — always need the LLM.
_SEMANTIC = [
    "scope_summary", "issuing_authority_location", "location_of_execution",
    "key_deliverables", "eligibility_conditions", "unusual_clauses", "penalty_clauses",
    "sow_page_refs", "procurement_model", "commercial_model",
    "tender_type_confidence", "tender_type_basis", "commercial_basis",
    "similar_work_pct", "similar_work_required_cr",
    "documents_required", "bidding_capacity", "multiplier_factor",
    "extras", "key_dates", "all_fields",
]

_SYSTEM = (
    "You extract facts from Indian government tender documents. Report ONLY what is "
    "written; use null/empty when absent; never invent. The text is segmented by "
    "'=== DOCUMENT: <file> | PAGE <n> ===' markers — cite document + page for all_fields/key_dates."
)


def _openai_fields(text: str, needed: list[str]) -> dict:
    if not settings.openai_api_key or not text:
        return {}
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        user = (
            f"Extract these fields: {needed}\n\n"
            "Return ONLY JSON. Shapes:\n"
            '  "eligibility_conditions": [string], "key_deliverables": [string],\n'
            '  "unusual_clauses": [{"text": string, "pages": string}], "penalty_clauses": [{"text": string, "pages": string}],\n'
            '  "procurement_model": string|null (EPC / O&M / PPP / Concession / Turnkey),\n'
            '  "commercial_model": string|null (client_pays_bidder / bidder_pays_concession / revenue_share / hybrid),\n'
            '  "tender_type_confidence": "High"|"Medium"|"Low"|null, "tender_type_basis": string|null,\n'
            '  "commercial_basis": string|null,\n'
            '  "estimated_value_cr": number|null (TOTAL estimated tender / project / contract value in ₹ crore — the headline cost, NOT EMD or turnover),\n'
            '  "similar_work_pct": number|null (the % of estimated cost the RFP demands for ONE similar completed work, e.g. 30/40/60),\n'
            '  "similar_work_required_cr": number|null (the ABSOLUTE ₹ crore value of one similar work, if the RFP states an amount instead of a %),\n'
            '  "documents_required": [string] (documents / certificates / profiles the BIDDER must submit — e.g. GST, PAN, ISO 9001, similar-work completion certificate, bank solvency, EMD DD, audited balance sheets),\n'
            '  "bidding_capacity": string|null (any bidding-capacity / available-capacity requirement the RFP states — include the formula or figure if given),\n'
            '  "multiplier_factor": string|null (any multiplier the RFP applies to past completed-work value when valuing experience, e.g. "2x for similar works"),\n'
            '  "extras": {"compliance_complexity": "Low"|"Medium"|"High" (ALWAYS pick one, based on the licences/registrations/certifications the RFP demands), "pricing_feasibility": string|null (price/L1 tenders only — can CS Direkt price competitively, and why), "epc_estimate_cr": number|null (L1 only — rough expected project cost in Rs crore)},\n'
            '  "sow_page_refs": string (page/section references for the scope of work, e.g. "p.34, p.37"),\n'
            '  "pre_bid_date": "YYYY-MM-DD"|null (the pre-bid meeting DATE if any pre-bid meeting/place is mentioned),\n'
            '  "key_dates": [{"label","value","document","page"}],\n'
            '  "all_fields": [{"label","value","document","page"}]\n'
            "Numbers (turnover/networth) in ₹ crore. Dates as YYYY-MM-DD.\n\n"
            f"Document text:\n---\n{text[:settings.extract_text_limit]}\n---"
        )
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        )
        return json.loads(resp.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001
        log.warning("openai extract failed: %s", exc)
        return {}


def vision_ocr(png_bytes: bytes) -> str:
    """OCR a rendered page image via gpt-4o-mini vision (last-resort, when text empty)."""
    if not settings.openai_api_key or not png_bytes:
        return ""
    try:
        import base64

        from openai import OpenAI

        b64 = base64.b64encode(png_bytes).decode()
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe ALL text in this scanned document page "
                     "exactly, preserving tables as markdown and reading order. Output text only."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("vision_ocr failed: %s", exc)
        return ""


def hybrid_extract(text: str) -> tuple[dict, dict]:
    py = python_fields(text)
    py_filled = [k for k, v in py.items() if v not in (None, "", [], {})]
    missing_regex = [k for k in _REGEXABLE if k not in py_filled]

    needed = _SEMANTIC + missing_regex
    llm = _openai_fields(text, needed)

    # Python wins on the fields it confidently extracted; LLM fills the rest.
    merged = {**llm, **{k: v for k, v in py.items() if v not in (None, "", [], {})}}
    # Coerce the LLM's string artefacts ("null", "[]", "n/a", …) to real None.
    _blank = {"null", "none", "n/a", "na", "[]", "{}", "-", ""}
    for k, v in list(merged.items()):
        if isinstance(v, str) and v.strip().lower() in _blank:
            merged[k] = None
    log_entry = {
        "python_filled": py_filled,
        "python_missed": missing_regex,
        "llm_filled": [k for k, v in llm.items() if v not in (None, "", [], {})],
    }
    return merged, log_entry
