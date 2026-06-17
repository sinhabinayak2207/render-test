"""Deterministic RULES qualifier (NO LLM).

Decides verdict / score / risk / urgency / eligibility from the extracted facts
and the customer's Profile. Faithful to the legacy engine:
  exclusion gate → score (scope 40 / dates 25 / financial 20 / docs 15) →
  verdict (≥elig / ≥partial) → financial-capacity demotion.
"""
from __future__ import annotations

import re
from datetime import date

from .profile import Profile

_WORD = re.compile(r"[a-z0-9]+")


def _norm(text: str) -> str:
    return " ".join(_WORD.findall((text or "").lower()))


def _present(phrase: str, hay: str) -> bool:
    """Whole-word / whole-phrase match (avoids 'expo' ⊂ 'export' false positives).

    `hay` is space-normalized tokens. Fuzzy matching is used ONLY for multi-word
    phrases, where it's safe; single words must match on word boundaries.
    """
    p = _norm(phrase)
    if not p:
        return False
    if f" {p} " in f" {hay} ":  # boundary-safe exact match
        return True
    if " " in p:  # multi-word phrase → allow fuzzy (spelling/spacing variants)
        try:
            from rapidfuzz import fuzz

            return fuzz.partial_ratio(p, hay) >= 92
        except Exception:  # noqa: BLE001
            return False
    return False


# ── scope / exclusion ─────────────────────────────────────────────────────────
def scope_check(text: str, profile: Profile) -> dict:
    hay = _norm(text)
    matched = [
        cat for cat, phrases in (profile.scope_keywords or {}).items()
        if any(_present(ph, hay) for ph in (phrases or []))
    ]
    in_scope = bool(matched) or any(_present(k, hay) for k in (profile.include_keywords or []))
    exclude_hit = any(_present(k, hay) for k in (profile.exclude_keywords or []))
    excluded = exclude_hit and not matched
    return {
        "matched_categories": matched,
        "in_scope": in_scope,
        "excluded": excluded,
        "exclude_reason": (
            "Out of scope — matched an exclusion keyword and no service-line anchor"
            if excluded else None
        ),
    }


def title_excluded(title: str, profile: Profile) -> bool:
    """Strong exclusion: an exclude keyword in the TITLE (the primary subject) —
    e.g. 'Rate contract for CLEANING of …' — overrides any incidental scope match."""
    hay = _norm(title)
    return any(_present(k, hay) for k in (profile.exclude_keywords or []))


def _fin_band(name: str, required: float | None, capacity: float | None,
              margin_pct: float = 5.0) -> dict | None:
    """Financial requirement vs capacity. `margin_pct` = client-configured partial
    margin (Settings):
      required <= capacity        -> qualifies WITHOUT margin (no flag -> ELIGIBLE)
      capacity < req <= +margin%  -> PARTIAL, highlighted (borderline)
      req beyond +margin%         -> PARTIAL, highlighted (over)
    """
    if not required or not capacity:
        return None
    ratio = required / capacity
    if ratio <= 1.0:
        return None  # within capacity — qualifies WITHOUT any margin (stays eligible)
    band = "borderline" if ratio <= 1 + margin_pct / 100 else "over"
    return {"field": name, "required": required, "capacity": capacity,
            "over_pct": round((ratio - 1) * 100, 1), "band": band, "highlight": True}


# ── helpers ───────────────────────────────────────────────────────────────────
def _to_cr(inr) -> float | None:
    return (inr / 1e7) if isinstance(inr, (int, float)) and inr else (0.0 if inr == 0 else None)


def _days_to(closing) -> int | None:
    try:
        return (date.fromisoformat(str(closing)[:10]) - date.today()).days
    except Exception:  # noqa: BLE001
        return None


# ── main ──────────────────────────────────────────────────────────────────────
def qualify(row: dict, profile: Profile) -> dict:
    # Match scope on the FOCUSED signal (title + LLM scope summary), not the full
    # raw_text — a 60-page doc mentioning "event"/"museum" in passing caused false
    # category matches and over-generous verdicts.
    text = " ".join(str(row.get(k) or "") for k in ("title", "scope_summary"))
    sc = scope_check(text, profile)

    # 1) Exclusion gate — out of scope, OR a strong exclusion keyword in the title.
    if sc["excluded"] or title_excluded(str(row.get("title") or ""), profile):
        reason = sc["exclude_reason"] or "Out of scope — exclusion keyword in the tender title"
        return {
            "verdict": "EXCLUDED", "competitiveness_score": 0,
            "score_breakdown": {"scope": 0, "dates": 0, "financial": 0, "docs": 0},
            "risk_level": "Low", "urgency": "LOW",
            "matched_categories": [], "excluded_reason": reason,
            "reasons_rejected": [reason], "reasons_qualified": [],
            "gaps_to_address": [], "eligibility_check": [], "eligibility_flags": [],
        }

    value_cr = _to_cr(row.get("estimated_value"))
    emd_cr = _to_cr(row.get("emd_amount"))
    pbg = row.get("pbg_percent")
    req_turnover = row.get("min_turnover_cr")
    req_networth = row.get("min_networth_cr")
    docs = row.get("downloaded_docs") or []
    has_boq = any("boq" in str(d.get("name", "")).lower() or "boq" in str(d.get("kind", "")).lower() for d in docs)
    has_rfp = any(str(d.get("format", "")) in ("digital_pdf", "scanned_pdf", "html", "vision") for d in docs)
    has_scope = bool(row.get("scope_summary"))
    unusual = len(row.get("unusual_clauses") or [])

    # 2) Score (scope 40 / dates 25 / financial 20 / docs 15)
    n = len(sc["matched_categories"])
    s_scope = 40 if n >= 3 else 30 if n == 2 else 20 if n == 1 else (10 if sc["in_scope"] else 0)
    if has_scope:
        s_scope = min(40, s_scope + 2)
    d = _days_to(row.get("closing_date"))
    s_dates = 25 if (d is not None and d > 20) else 18 if (d is not None and 10 <= d <= 20) else 10 if (d is not None and 7 <= d < 10) else 0
    floor_failed = value_cr is not None and 0 < value_cr < profile.min_tender_value_cr
    over_max = profile.max_tender_value_cr is not None and value_cr and value_cr > profile.max_tender_value_cr
    s_fin = 0 if floor_failed else 20
    if emd_cr and emd_cr > profile.emd_threshold_cr:
        s_fin -= 5
    if pbg and pbg > profile.pbg_threshold_pct:
        s_fin -= 5
    s_fin = max(0, s_fin)
    s_docs = min(15, (8 if has_boq else 0) + (4 if has_rfp else 0) + (3 if has_scope else 0))
    total = s_scope + s_dates + s_fin + s_docs

    # 3) Verdict from score, then gates + demotion ladder.
    reasons_q, reasons_r, gaps = [], [], []
    verdict = "ELIGIBLE" if total >= profile.eligible_min_score else "PARTIAL" if total >= profile.partial_min_score else "INELIGIBLE"

    if floor_failed:
        verdict = "INELIGIBLE"
        reasons_r.append(f"Value ₹{value_cr:.2f} Cr below the ₹{profile.min_tender_value_cr} Cr floor")
    elif over_max:
        verdict = "INELIGIBLE"
        reasons_r.append(f"Value ₹{value_cr:.2f} Cr above the ₹{profile.max_tender_value_cr} Cr ceiling")
    elif not sc["in_scope"]:
        verdict = "INELIGIBLE"
        reasons_r.append("No CS Direkt service-line match in the documents")
    elif not value_cr and not sc["matched_categories"]:
        verdict = "INELIGIBLE"
        reasons_r.append("Value not disclosed and no clear scope match")

    # financial-capacity tolerance bands (never auto-reject)
    fin_flags: list[dict] = []
    _pm = profile.partial_margins or {}
    for _nm, _req, _cap, _mkey in (("turnover", req_turnover, profile.turnover_3yr_avg_cr, "turnover_3yr_avg_cr"),
                                   ("net_worth", req_networth, profile.net_worth_latest_cr, "net_worth_latest_cr")):
        try:
            _margin = float(_pm[_mkey]) if _pm.get(_mkey) is not None else profile.partial_margin_pct
        except (TypeError, ValueError, KeyError):
            _margin = profile.partial_margin_pct
        fl = _fin_band(_nm, _req, _cap, _margin)
        label = _nm.replace("_", " ").title()
        if fl is None:
            if _req:
                reasons_q.append(f"{label} ₹{_req} Cr within capacity ₹{_cap} Cr")
            continue
        fl["margin_pct"] = _margin
        fin_flags.append(fl)
        if verdict == "ELIGIBLE":
            verdict = "PARTIAL"  # any margin invoked → not 100% qualified → PARTIAL
        if fl["band"] == "borderline":
            reasons_r.append(f"{label} required ₹{_req} Cr exceeds capacity ₹{_cap} Cr within +{_margin:.0f}% margin (borderline → PARTIAL, highlighted)")
        else:
            reasons_r.append(f"{label} required ₹{_req} Cr is {fl['over_pct']}% over capacity ₹{_cap} Cr — PARTIAL via JV/consortium (highlighted)")

    if sc["matched_categories"]:
        reasons_q.append("Scope matches: " + ", ".join(sc["matched_categories"]))
    if not value_cr:
        gaps.append("Tender value not disclosed — await BOQ")
    if not has_boq:
        gaps.append("BOQ not yet available")
    if verdict in ("PARTIAL", "INELIGIBLE") and not reasons_r:
        reasons_r.append(f"Score {total} below ELIGIBLE threshold ({profile.eligible_min_score})")

    urgency = "HIGH" if (d is not None and d <= 7) else "MEDIUM" if (d is not None and d <= 15) else "LOW"
    risk = "High" if ((pbg and pbg > profile.pbg_threshold_pct) or unusual >= 2) else "Medium" if (len(gaps) >= 2 or unusual >= 1) else "Low"

    fin_status = "[!]" if fin_flags else "[OK]"  # highlighted when any band tripped
    if req_turnover:
        fin_detail = f"Turnover required ≈ ₹{req_turnover} Cr — CS Direkt 3-yr avg ₹{profile.turnover_3yr_avg_cr} Cr → {fin_status}."
    else:
        fin_detail = f"No turnover threshold extracted; CS Direkt 3-yr avg ₹{profile.turnover_3yr_avg_cr} Cr."
    if req_networth:
        fin_detail += f" Net worth required ≈ ₹{req_networth} Cr vs ₹{profile.net_worth_latest_cr} Cr."
    n_clauses = len(row.get("eligibility_conditions") or [])

    # Experience: SECTOR-WISE — the largest similar work in the tender's matched category
    # (from the portfolio) vs the RFP's similar-work tier (4o-mini reads the RFP; else % of value).
    from .portfolio import sector_largest

    _ed = row.get("extracted_data") or {}
    _sw_req = _ed.get("similar_work_required_cr")
    _sw_req = float(_sw_req) if isinstance(_sw_req, (int, float)) else None
    _sw_pct = _ed.get("similar_work_pct")
    _sw_pct = float(_sw_pct) if isinstance(_sw_pct, (int, float)) else profile.similar_work_pct
    _sec_largest, _sec_proj, _sec_cnt = sector_largest(profile.portfolio, sc["matched_categories"])
    _largest = _sec_largest or profile.largest_similar_work_cr
    _cnt = _sec_cnt or profile.similar_works_count
    _proj = f"{_sec_proj} (₹{_largest} Cr)" if _sec_proj else f"₹{_largest} Cr"
    if _sw_req:
        _req_sim, _basis = round(_sw_req, 2), "RFP-stated"
    elif value_cr:
        _req_sim, _basis = round(value_cr * _sw_pct / 100, 2), f"{_sw_pct:.0f}% of ₹{value_cr:.2f} Cr"
    else:
        _req_sim = None
    if _req_sim is None:
        exp_status = "[?]"
        exp_detail = f"Similar-work tier not computable (value undisclosed); CS Direkt's largest matching work: {_proj}, {_cnt} similar projects."
    elif _largest >= _req_sim:
        exp_status = "[OK]"
        exp_detail = f"Requires one similar work ≈ ₹{_req_sim} Cr ({_basis}); CS Direkt's largest matching work {_proj} ≥ requirement → [OK] ({_cnt} similar projects)."
    elif _largest >= _req_sim * 0.85:
        exp_status = "[!]"
        exp_detail = f"Requires one similar work ≈ ₹{_req_sim} Cr ({_basis}); close to CS Direkt's largest matching work {_proj} — confirm a qualifying project."
    else:
        exp_status = "[!]"
        exp_detail = f"Requires one similar work ≈ ₹{_req_sim} Cr ({_basis}) — exceeds CS Direkt's largest matching work {_proj}; bid via JV/consortium."

    eligibility_check = [
        {"dimension": "Legal", "status": "[LIKELY OK]",
         "detail": "Statutory registrations (GST/PAN/ISO 9001) held; verify each named document is current."},
        {"dimension": "Financial", "status": fin_status, "detail": fin_detail},
        {"dimension": "Experience", "status": exp_status, "detail": exp_detail},
        {"dimension": "Special", "status": "[OK]" if sc["matched_categories"] else "[?]",
         "detail": "Scope matches: " + (", ".join(sc["matched_categories"]) if sc["matched_categories"] else "no service-line anchor.")},
    ]

    return {
        "verdict": verdict,
        "competitiveness_score": 100 if verdict == "ELIGIBLE" else total,
        "score_breakdown": {"scope": s_scope, "dates": s_dates, "financial": s_fin, "docs": s_docs},
        "risk_level": risk,
        "urgency": urgency,
        "matched_categories": sc["matched_categories"],
        "reasons_qualified": reasons_q,
        "reasons_rejected": reasons_r,
        "gaps_to_address": gaps,
        "eligibility_check": eligibility_check,
        "eligibility_flags": fin_flags,
        "excluded_reason": None,
    }
