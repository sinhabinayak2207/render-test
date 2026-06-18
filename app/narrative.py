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
    "recommendation, key insight and risk; flag rejection-worthy risks clearly. "
    "Base EVERY recommendation strictly on CS Direkt's documented capabilities, financials and past "
    "projects — never assume capability beyond what the profile/portfolio shows. Use cs_direkt_profile "
    "(scope_description, in/out-of-scope keywords, turnover, net worth, bank solvency, EMD/PBG capacity, "
    "legal items) to judge fit: compare the tender's stated requirements against these ACTUAL figures and "
    "CITE them — e.g. 'needs Rs.27.66 Cr turnover vs CS Direkt's Rs.103.79 Cr 3-yr avg → met', or 'scope is "
    "civil construction, which is in CS Direkt's out-of-scope keywords → no fit'. For PARTIAL/INELIGIBLE "
    "tenders, state the tender type, the specific gap that blocks eligibility, and exactly what CS Direkt "
    "would need to fulfil to qualify. "
    "Be SPECIFIC and analytical — never generic boilerplate; every risk, compliance note and recommendation "
    "must reference THIS tender's actual terms. When the source text carries a page/section marker, cite it "
    "(e.g. 'per RFP p.12'). Explain the procurement model's basis and the commercial structure's payment "
    "terms. For penalty clauses, state the penalty's cap/end period. Rate compliance complexity Low/Medium/"
    "High WITH the reason. For experience, refer to CS Direkt's completion certificates for similar work. If "
    "the documents are too thin to support a real analysis, SAY SO explicitly instead of guessing. "
    "For pre_bid_queries, act as an EXPERT TENDER CONSULTANT whose goal is to MAXIMISE CS Direkt's chance to "
    "qualify and win: compare every tender requirement against CS Direkt's actual credentials/capabilities, "
    "and find where an eligibility / turnover / experience / EMD / project-completion / OEM / technical-spec "
    "/ payment / warranty / SLA / contractual clause could reasonably be clarified, relaxed, modified or made "
    "more inclusive through a pre-bid query. Raise ONLY meaningful, professionally-defensible questions a real "
    "bidder would ask. Prioritise (in order): eligibility, turnover/financial, technical, experience, EMD, "
    "consortium/JV/subcontracting, payment, commercial/contractual. Rank each 'Critical' (must ask) or "
    "'Important' (should ask). Return ONLY JSON."
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
        # Full CS Direkt profile so Claude can compare the tender's requirements against the
        # company's ACTUAL scope, keywords, financials and legal standing (cite exact figures).
        "cs_direkt_profile": ({
            "scope_description": getattr(profile, "scope_description", "") or "",
            "in_scope_keywords": (getattr(profile, "include_keywords", None) or [])[:80],
            "out_of_scope_keywords": (getattr(profile, "exclude_keywords", None) or [])[:40],
            "turnover_3yr_avg_cr": getattr(profile, "turnover_3yr_avg_cr", None),
            "turnover_last_year_cr": getattr(profile, "turnover_last_year_cr", None),
            "net_worth_latest_cr": getattr(profile, "net_worth_latest_cr", None),
            "net_worth_3yr_avg_cr": getattr(profile, "net_worth_3yr_avg_cr", None),
            "bank_solvency_cr": getattr(profile, "bank_solvency_cr", None),
            "emd_capacity_cr": getattr(profile, "emd_threshold_cr", None),
            "pbg_capacity_pct": getattr(profile, "pbg_threshold_pct", None),
            "min_tender_value_cr": getattr(profile, "min_tender_value_cr", None),
            "max_tender_value_cr": getattr(profile, "max_tender_value_cr", None),
            "legal_items": getattr(profile, "legal_items", None) or [],
        } if profile else {}),
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
            '  "gaps_to_address": [string] (compare the TENDER\'s stated requirements against CS Direkt\'s ACTUAL financials, past projects and registrations; list each tender-spec requirement CS Direkt does NOT meet + how to close it — e.g. "RFP requires ISO 27001 (p5 of RFP); CS Direkt does not hold it — obtain before bidding" or "turnover bar Rs.27.66 Cr exceeds single-entity reach — bid via JV". For ELIGIBLE: minor pre-award items or [] if none),\n'
            '  "pre_bid_queries": [{"priority": "Critical"|"Important", "clause_reference": string (clause no./section/page), "existing_requirement": string (what the RFP currently demands), "observation": string (the gap/concern vs CS Direkt\'s credentials), "question": string (the exact question to put to the authority), "strategic_objective": string (what asking it achieves for CS Direkt), "expected_benefit": string (benefit if the authority accepts the clarification)}]\n'
            '}'
        )
    else:  # INELIGIBLE / EXCLUDED
        keys = (
            '{\n'
            '  "key_business_insight": string (<=30 words, prefix "CRITICAL DROP: "),\n'
            '  "disqualification_triggers": [{"name": string, "evidence": string}],\n'
            '  "business_logic_explanation": string (3-4 plain sentences),\n'
            '  "pre_bid_queries": [{"priority": "Critical"|"Important", "clause_reference": string, "existing_requirement": string, "observation": string, "question": string, "strategic_objective": string, "expected_benefit": string}] (queries that could realistically make this tender achievable for CS Direkt — e.g. relax/clarify a hard eligibility bar; [] if no defensible query exists)\n'
            '}'
        )
    user = "Tender:\n" + json.dumps(meta, ensure_ascii=False, default=str) + "\n\nReturn ONLY this JSON:\n" + keys
    try:
        import anthropic
    except Exception:  # noqa: BLE001
        return {}
    # Hard per-request timeout: a hung Claude call would otherwise keep the per-tender
    # worker thread alive past the run (the executor timeout can't kill it), leaking threads.
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=90.0, max_retries=1)
    # Retry once: a transient Claude failure used to silently drop the whole narrative
    # (e.g. key_business_insight came back blank on some tenders).
    for attempt in (1, 2):
        try:
            resp = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=4000,   # enriched pre-bid queries (6 fields each) overflowed 1500 -> truncated/invalid JSON
                temperature=0.2,
                system=_SYSTEM,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(getattr(b, "text", "") for b in resp.content)
            text = text[text.find("{"): text.rfind("}") + 1]
            data = json.loads(text)
            # Keep empty lists/dicts: gaps_to_address=[] is Claude's EXPLICIT "no gaps" signal,
            # and dropping it left a stale rules/extraction gaps list on the row. Strip only
            # genuinely-absent values (None / empty string).
            out = {k: v for k, v in data.items() if v is not None and v != ""}
            if out:
                return out
        except Exception as exc:  # noqa: BLE001
            log.warning("generate_narrative attempt %d failed: %s", attempt, exc)
    return {}
