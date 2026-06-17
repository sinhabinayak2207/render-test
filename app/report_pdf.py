"""Tender Intelligence Report → PDF via the bundled Jinja2 + WeasyPrint template.

Fetches a run's tenders (default = all) + profile from Supabase, maps them to the
template's CONTEXT shape (see app/report_template/sample_data shape) and renders
app/report_template/templates/combined_report.html.j2. EXCLUDED tenders are dropped.

WeasyPrint needs system libs (pango/cairo/gdk-pixbuf): present in WSL + installable
on Render via apt. Run:  python -m app.report_pdf [run_id]
"""
from __future__ import annotations

import json
import logging
import sys
import urllib.request
from datetime import date
from pathlib import Path

from .config import settings
from .portfolio import PORTFOLIO
from .profile import Profile

log = logging.getLogger("report_pdf")

_H = {"apikey": settings.supabase_service_key, "Authorization": f"Bearer {settings.supabase_service_key}"}
VORDER = {"ELIGIBLE": 0, "PARTIAL": 1, "INELIGIBLE": 2, "EXCLUDED": 3, "PENDING": 4}
VCLASS = {"ELIGIBLE": "eligible", "PARTIAL": "partial", "INELIGIBLE": "rejected", "PENDING": "rejected"}
RISKCLASS = {"low": "low", "medium": "medium", "high": "high"}
_EMPTY = {"", "[]", "{}", "null", "none", "n/a", "na", "-", "—", "[ ]"}


def _get(path: str):
    return json.load(urllib.request.urlopen(urllib.request.Request(f"{settings.supabase_url}/rest/v1/{path}", headers=_H), timeout=60))


def _clean(v):
    if v in (None, [], {}):
        return None
    if isinstance(v, str) and v.strip().lower() in _EMPTY:
        return None
    return v


def _money(inr) -> str:
    if not inr:
        return "Value not disclosed"
    cr = inr / 1e7
    return f"Rs. {cr:.2f} Cr" if cr >= 0.01 else "Value not disclosed"


def _emd(inr) -> str:
    if not inr:
        return "—"
    lakh = inr / 1e5
    return f"Rs. {inr/1e7:.2f} Cr" if lakh >= 100 else f"Rs. {lakh:.2f} Lakh"


def _clause(c) -> str:
    if isinstance(c, dict):
        return (c.get("text") or "") + (f"  [pp {c['pages']}]" if c.get("pages") else "")
    return str(c)


def _slist(items, fmt=str):
    return [fmt(i) for i in (items or []) if _clean(i) is not None]


def _status_class(status: str) -> str:
    s = (status or "").lower()
    if "ok" in s:
        return "pass"
    if "fail" in s:
        return "fail"
    return "warn"  # [?], [!], [assumed], review


def _elig_rows(t):
    out = []
    for r in (t.get("eligibility_check") or []):
        out.append({"dimension": r.get("dimension", ""), "status": (r.get("status") or "").strip("[]"),
                    "status_class": _status_class(r.get("status")), "detail": r.get("detail", "")})
    return out


def _prebid(t):
    out = []
    for q in (t.get("pre_bid_queries") or []):
        if isinstance(q, dict):
            txt = q.get("question") or ""
            if q.get("rationale"):
                txt += f"  (Rationale: {q['rationale']})"
            if txt:
                out.append(txt)
        elif _clean(q):
            out.append(str(q))
    return out


def _docs(t):
    out = []
    for d in (t.get("downloaded_docs") or []):
        if str(d.get("format") or "").lower() == "html" or str(d.get("kind") or "").lower() == "html":
            continue
        u = d.get("storage_url") or d.get("public_url")
        if u:
            out.append({"kind": (d.get("kind") or "doc"), "url": u, "label": d.get("name") or "Document"})
    return out


def _tctx(t):
    ed = t.get("extracted_data") or {}
    ex = (ed.get("extras") or {}) if isinstance(ed, dict) else {}
    v = t.get("verdict")
    dur = t.get("project_duration")
    dur = f"{dur} days" if str(dur).strip().isdigit() else (dur or "—")
    risk = (t.get("risk_level") or "Low")
    return {
        "verdict": v, "verdict_class": VCLASS.get(v, "rejected"),
        "deadline_state": "ok", "days_to_close": None, "closing_date": t.get("closing_date"),
        "title": t.get("title") or "(untitled)", "authority": t.get("issuing_authority") or "—",
        "issuing_authority_location": t.get("issuing_authority_location"),
        "authority_contact": t.get("authority_contact"), "portal": t.get("portal_name") or "TenderKart",
        "reference_number": t.get("reference_number"), "estimated_value": _money(t.get("estimated_value")),
        "emd": _emd(t.get("emd_amount")), "published": (t.get("published_at") or "")[:10] or None,
        "submission_deadline": t.get("closing_date"), "technical_opening": t.get("opening_date") or "—",
        "tender_type": t.get("tender_type") or "—", "tender_type_confidence": ed.get("tender_type_confidence") or "",
        "tender_type_reasoning": ed.get("tender_type_basis") or "",
        "procurement_model": t.get("procurement_model") or "—",
        "commercial_model": t.get("commercial_model") or "—", "commercial_model_reasoning": ed.get("commercial_basis") or "",
        "fit_score_10": f"{(t.get('competitiveness_score') or 0)/10:.1f}",
        "strategic_fit_basis": t.get("strategic_fit_basis") or "", "recommendation_narrative": t.get("narrative_fit") or "",
        "scope_summary": t.get("scope_summary") or "—", "deliverables": _slist(t.get("key_deliverables")),
        "project_duration": dur, "location_of_execution": t.get("location_of_execution") or "—",
        "sow_page_refs": _clean(t.get("sow_page_refs")) or "—",
        "unusual_clauses": _slist(t.get("unusual_clauses"), _clause), "penalty_clauses": _slist(t.get("penalty_clauses"), _clause),
        "compliance_complexity": ex.get("compliance_complexity") or "—", "compliance_basis": t.get("compliance_basis") or "",
        "risk_level": risk, "risk_class": RISKCLASS.get(risk.lower(), "medium"),
        "risk_layperson_explanation": t.get("risk_layperson_explanation") or "",
        "eligibility_rows": _elig_rows(t), "eligibility_conditions": _slist(t.get("eligibility_conditions")),
        "gaps": _slist(t.get("gaps_to_address")), "pre_bid_queries": _prebid(t),
        "pricing_feasibility": ex.get("pricing_feasibility") or "—",
        "epc_estimate": f"Rs. {ex.get('epc_estimate_cr')} Cr" if ex.get("epc_estimate_cr") else "—",
        "source_docs": _docs(t), "input_coverage": "", "page_refs": {}, "data_conflicts": [],
        "eligibility_flags": [
            {"field": (fl.get("field", "").replace("_", " ").title()), "required": fl.get("required"),
             "capacity": fl.get("capacity"), "over_pct": fl.get("over_pct"),
             "borderline": fl.get("band") == "borderline"}
            for fl in (t.get("eligibility_flags") or [])
        ],
        "partial_reasons": _slist(t.get("reasons_rejected")),
        "reasons": _slist(t.get("reasons_qualified")) or _slist(t.get("reasons_rejected")),
    }


def _rctx(t):
    return {
        "verdict": "REJECTED", "title": t.get("title") or "(untitled)", "authority": t.get("issuing_authority") or "—",
        "portal": t.get("portal_name") or "TenderKart", "reference_number": t.get("reference_number"),
        "estimated_value": _money(t.get("estimated_value")), "closing_date": t.get("closing_date"),
        "matched_keyword": t.get("matched_keyword") or "—",
        "disqualification_triggers": [{"name": d.get("name", ""), "evidence": d.get("evidence", "")}
                                      for d in (t.get("disqualification_triggers") or []) if isinstance(d, dict)],
        "business_logic_explanation": t.get("business_logic_explanation") or "",
        "reasons": _slist(t.get("reasons_rejected")),
    }


def _profile_ctx() -> dict:
    p = Profile()
    row = (_get("company_profiles?user_id=is.null&select=*") or [None])[0]
    if row:
        for attr in ("company_name", "turnover_latest_cr", "turnover_last_year_cr", "turnover_3yr_avg_cr",
                     "net_worth_latest_cr", "net_worth_3yr_avg_cr", "bank_solvency_cr", "min_tender_value_cr",
                     "max_tender_value_cr", "emd_threshold_cr", "pbg_threshold_pct",
                     "largest_similar_work_cr", "similar_works_count", "exclude_keywords", "scope_keywords",
                     "gst_number", "pan_number", "certifications", "contractor_class", "can_form_jv",
                     "auto_reject_risks", "no_go_locations", "partial_margin_pct", "legal_items",
                     "analysis_instructions"):
            val = row.get(attr)
            if val is not None:
                setattr(p, attr, val)
    pos = sorted({kw for v in (p.scope_keywords or {}).values() for kw in v})
    return {
        "company_name": p.company_name, "contact_email": p.contact_email,
        "min_tender_value_cr": p.min_tender_value_cr, "max_tender_value_cr": p.max_tender_value_cr or "no limit",
        "positive_keywords": ", ".join(pos), "negative_keywords": ", ".join(p.exclude_keywords or []),
        "min_days_to_close": p.min_days_to_close,
        "turnover_last": p.turnover_last_year_cr, "turnover_3yr": p.turnover_3yr_avg_cr,
        "net_worth_latest": p.net_worth_latest_cr, "net_worth_3yr": p.net_worth_3yr_avg_cr,
        "solvency": p.bank_solvency_cr, "max_emd": p.emd_threshold_cr, "max_pbg": p.pbg_threshold_pct,
        "largest_similar": p.largest_similar_work_cr, "similar_count": p.similar_works_count,
        "past_sectors": ", ".join(p.past_sectors or []),
        "gst": p.gst_number or "—", "pan": p.pan_number or "—",
        "certifications": ", ".join(p.certifications or []),
        "contractor_class": p.contractor_class or "none", "can_jv": "Yes" if p.can_form_jv else "No",
        "regions": ", ".join(p.regions or []), "special_status": ", ".join(p.special_status or []) or "none",
        "auto_reject_risks": p.auto_reject_risks or "none configured",
        "analysis_instructions": p.analysis_instructions or "—",
        "legal_items": p.legal_items or [],
        "partial_margin_pct": p.partial_margin_pct,
        "pref_sectors": ", ".join(p.preferred_sectors_ranked or []),
        "value_sweet_spot": f"{p.value_sweet_spot_cr[0]} - {p.value_sweet_spot_cr[1]}" if p.value_sweet_spot_cr else "—",
        "pref_clients": ", ".join(p.preferred_client_types or []), "pref_geo": ", ".join(p.preferred_geographies or []),
        "pref_days": p.preferred_min_days, "risk_appetite": p.risk_appetite,
        "always_prioritize": p.always_prioritize, "always_avoid": p.always_avoid,
    }


def _build_context(run_id: str | None) -> dict:
    if run_id:
        tenders = _get(f"tenders?run_id=eq.{run_id}&select=*")
        cycle = run_id[:8]
    else:
        tenders = _get("tenders?select=*&order=created_at.desc&limit=1000")
        cycle = "ALL"
    tenders = [t for t in tenders if t.get("verdict") != "EXCLUDED"]
    tenders.sort(key=lambda t: (VORDER.get(t.get("verdict"), 9), -(t.get("competitiveness_score") or 0)))

    elig = [t for t in tenders if t.get("verdict") == "ELIGIBLE"]
    part = [t for t in tenders if t.get("verdict") == "PARTIAL"]
    rej = [t for t in tenders if t.get("verdict") == "INELIGIBLE"]

    # exec-summary grouped by matched keyword
    groups: dict[str, list] = {}
    for t in tenders:
        groups.setdefault(t.get("matched_keyword") or "(unmatched)", []).append({
            "title": t.get("title") or "(untitled)", "authority": t.get("issuing_authority") or "—",
            "estimated_value": _money(t.get("estimated_value")), "verdict": t.get("verdict"),
            "verdict_class": VCLASS.get(t.get("verdict"), "rejected"),
            "key_business_insight": (t.get("key_business_insight") or t.get("excluded_reason") or "")[:200],
        })
    grouped = sorted(groups.items(), key=lambda kv: -max((VORDER.get("ELIGIBLE", 0) == VORDER.get(r["verdict"]) for r in kv[1]), default=0))

    return {
        "doc_title": "CSDirekt Tender Intelligence Report", "generated_on": date.today().isoformat(),
        "cycle_id": cycle, "cost_footer": "", "profile": _profile_ctx(),
        "counts": {"total": len(tenders), "eligible": len(elig), "partial": len(part), "rejected": len(rej)},
        "grouped": grouped,
        "section_a": [_tctx(t) for t in elig], "section_b": [_tctx(t) for t in part], "section_c": [_rctx(t) for t in rej],
        "detail_note": "Section C entries are retained for audit traceability. EXCLUDED (out-of-scope) tenders are omitted.",
        "show_appendix": True,
    }


def build_pdf(run_id: str | None = None, out_path: str = "/mnt/c/Users/sinha/Downloads/CSD_tender_report.pdf") -> str:
    ctx = _build_context(run_id)
    try:
        from .report_template.renderer import render_to_pdf
        render_to_pdf(template="combined_report.html.j2", context=ctx, out_path=Path(out_path))
    except Exception as exc:  # noqa: BLE001 — WeasyPrint needs GTK libs (absent on Windows) → fall back.
        log.warning("WeasyPrint render failed (%s) — using reportlab fallback", exc)
        _render_reportlab(ctx, out_path)
    return out_path


def _render_reportlab(ctx: dict, out_path: str) -> None:
    """Pure-Python PDF fallback (works where WeasyPrint's system libs are absent)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=ss["Title"], fontSize=18, spaceAfter=4)
    H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=4,
                        textColor=colors.HexColor("#1f2937"))
    TT = ParagraphStyle("TT", parent=ss["Heading3"], fontSize=11, spaceBefore=8, spaceAfter=1)
    BODY = ParagraphStyle("BODY", parent=ss["Normal"], fontSize=9, leading=12)
    SMALL = ParagraphStyle("SMALL", parent=ss["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#6b7280"))

    def esc(s):
        return str(s if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    c = ctx["counts"]
    story = [
        Paragraph(esc(ctx["doc_title"]), H1),
        Paragraph(f"Generated {esc(ctx['generated_on'])} &middot; Cycle {esc(ctx['cycle_id'])}", SMALL),
        Paragraph(f"<b>{c['total']}</b> tenders &middot; <b>{c['eligible']}</b> eligible &middot; "
                  f"<b>{c['partial']}</b> partially eligible &middot; <b>{c['rejected']}</b> rejected", BODY),
        Spacer(1, 6),
    ]
    for key, label in (("section_a", "Eligible"), ("section_b", "Partially Eligible"), ("section_c", "Rejected")):
        items = ctx.get(key) or []
        if not items:
            continue
        story += [HRFlowable(width="100%", color=colors.HexColor("#d1d5db")), Paragraph(f"{label} ({len(items)})", H2)]
        for t in items:
            story.append(Paragraph(esc(t.get("title")), TT))
            meta = f"{esc(t.get('authority'))} &middot; {esc(t.get('estimated_value'))}"
            if t.get("fit_score_10"):
                meta += f" &middot; Fit {esc(t['fit_score_10'])}/10"
            if t.get("closing_date"):
                meta += f" &middot; closes {esc(str(t['closing_date'])[:10])}"
            story.append(Paragraph(meta, SMALL))
            scope = t.get("scope_summary")
            if scope and scope != "—":
                story.append(Paragraph(f"<b>Scope:</b> {esc(scope)[:500]}", BODY))
            reasons = t.get("partial_reasons") or t.get("reasons") or []
            if reasons:
                lbl = "Why partial" if key == "section_b" else ("Why rejected" if key == "section_c" else "Notes")
                story.append(Paragraph(f"<b>{lbl}:</b> {esc('; '.join(reasons[:5]))}", BODY))
            for fl in (t.get("eligibility_flags") or []):
                story.append(Paragraph(
                    f"[!] {esc(fl.get('field'))}: required {esc(fl.get('required'))} vs capacity "
                    f"{esc(fl.get('capacity'))} ({esc(fl.get('over_pct'))}% over)", SMALL))
            story.append(Spacer(1, 5))

    SimpleDocTemplate(out_path, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                      topMargin=14 * mm, bottomMargin=14 * mm).build(story)


if __name__ == "__main__":
    rid = sys.argv[1] if len(sys.argv) > 1 else None
    print("PDF written:", build_pdf(rid))
