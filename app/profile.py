"""Per-customer Bidding/Scope profile (the editable RULES config).

Loaded from Supabase `company_profiles`; falls back to CS Direkt defaults so the
qualifier works even before a profile row exists. Multi-tenant: one row per
user_id; the pipeline uses the default row (user_id IS NULL).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .supabase_client import service_client

log = logging.getLogger("profile")

_DEFAULT_SCOPE = {
    "Museums": ["museum", "gallery", "interpretation centre", "interpretation center", "exhibit", "diorama"],
    "Exhibitions": ["exhibition", "expo", "pavilion", "trade fair", "display"],
    "MICE": ["conference", "convention", "summit", "seminar", "mice"],
    "Events": ["event", "ceremony", "festival", "celebration", "inauguration"],
    "Light & Sound": ["light and sound", "son et lumiere", "sound and light", "projection mapping", "laser show"],
    "Science Centres": ["science centre", "science center", "planetarium", "science city", "innovation hub"],
    "Heritage": ["heritage", "monument", "conservation", "restoration"],
    "Tourism": ["tourism", "tourist", "destination development", "experience centre", "visitor centre", "visitor center"],
    "Content": ["audio visual", "immersive", "augmented reality", "virtual reality", "hologram", "multimedia", "documentary film"],
}
_DEFAULT_EXCLUDE = [
    "road construction", "civil construction", "building construction", "false ceiling",
    "supply of material", "material supply", "passenger lift", "boundary wall", "manpower supply",
    "housekeeping", "security guard", "pest control", "furniture supply", "ambulance",
    "printer", "laptop", "cctv", "firefighting",
]


@dataclass
class Profile:
    company_name: str = "CS Direkt"
    turnover_latest_cr: float = 103.79      # legacy alias of the capacity gate
    turnover_last_year_cr: float = 104.27   # turnover, latest FY (display)
    turnover_3yr_avg_cr: float = 103.79     # turnover, 3-yr avg — the capacity GATE
    net_worth_latest_cr: float = 35.80      # net worth latest — the capacity GATE
    net_worth_3yr_avg_cr: float = 29.66
    min_tender_value_cr: float = 0.35
    max_tender_value_cr: float | None = None
    emd_threshold_cr: float = 0.25
    pbg_threshold_pct: float = 10.0
    eligible_min_score: int = 65
    partial_min_score: int = 40
    largest_similar_work_cr: float = 100.0  # Jyotisar Museum, Kurukshetra (₹100 Cr)
    similar_works_count: int = 27           # CS Direkt portfolio (credentials doc)
    similar_work_pct: float = 40.0          # tender's "one similar work" tier = % of value
    scope_keywords: dict = field(default_factory=lambda: dict(_DEFAULT_SCOPE))
    include_keywords: list = field(default_factory=list)
    exclude_keywords: list = field(default_factory=lambda: list(_DEFAULT_EXCLUDE))
    portfolio: list = field(default_factory=list)   # past projects (experience evidence)
    # ── full intake profile (CS Direkt defaults; editable via Settings later) ──
    contact_email: str = "partner@csdirekt.com"
    bank_solvency_cr: float = 30.65
    min_days_to_close: int = 7
    past_sectors: list = field(default_factory=lambda: ["Museums", "Science Centres", "Heritage", "Exhibitions", "Sound & Light", "Events"])
    held_registrations: list = field(default_factory=lambda: ["GST", "PAN", "ISO 9001", "EPF", "ESIC"])
    contractor_class: str | None = None
    can_form_jv: bool = True
    regions: list = field(default_factory=lambda: ["pan-India"])
    special_status: list = field(default_factory=list)
    preferred_sectors_ranked: list = field(default_factory=lambda: ["Museums", "Light & Sound", "Exhibitions", "Science Centres"])
    value_sweet_spot_cr: list = field(default_factory=lambda: [5, 50])
    preferred_client_types: list = field(default_factory=lambda: ["Central", "State", "PSU"])
    preferred_geographies: list = field(default_factory=lambda: ["any"])
    preferred_min_days: int = 15
    risk_appetite: str = "medium"
    always_prioritize: str = "museums, planetariums, light & sound"
    always_avoid: str = "pure civil / fit-out / supply-only"
    # ── legal + others (editable from Settings) ──
    gst_number: str = ""
    pan_number: str = ""
    certifications: list = field(default_factory=lambda: ["GST", "PAN", "ISO 9001", "EPF", "ESIC"])
    auto_reject_risks: str = ""   # free NL risk factors → fed to Claude during analysis
    no_go_locations: list = field(default_factory=list)     # vestigial
    partial_margin_pct: float = 5.0   # global default margin (fallback)
    partial_margins: dict = field(default_factory=dict)   # per-field margin %: {field_key: pct}
    legal_items: list = field(default_factory=list)        # ["legal/compliance item", ...]
    analysis_instructions: str = ""   # free NL guidance fed to Claude during narrative


def _attach_portfolio(prof: "Profile", user_id: str | None) -> "Profile":
    try:
        from .portfolio import load_portfolio
        prof.portfolio = load_portfolio(user_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("portfolio load failed: %s", exc)
    return prof


def _f(v, default):
    try:
        return float(v) if v is not None else default
    except Exception:  # noqa: BLE001
        return default


def load_profile(user_id: str | None = None) -> Profile:
    try:
        q = service_client().table("company_profiles").select("*")
        q = q.eq("user_id", user_id) if user_id else q.is_("user_id", "null")
        res = q.limit(1).execute()
        if res.data:
            r = res.data[0]
            return _attach_portfolio(Profile(
                company_name=r.get("company_name") or "CS Direkt",
                turnover_latest_cr=_f(r.get("turnover_latest_cr"), 103.79),
                net_worth_latest_cr=_f(r.get("net_worth_latest_cr"), 35.80),
                min_tender_value_cr=_f(r.get("min_tender_value_cr"), 0.35),
                max_tender_value_cr=(_f(r.get("max_tender_value_cr"), None) if r.get("max_tender_value_cr") is not None else None),
                emd_threshold_cr=_f(r.get("emd_threshold_cr"), 0.25),
                pbg_threshold_pct=_f(r.get("pbg_threshold_pct"), 10.0),
                eligible_min_score=int(_f(r.get("eligible_min_score"), 65)),
                partial_min_score=int(_f(r.get("partial_min_score"), 40)),
                largest_similar_work_cr=_f(r.get("largest_similar_work_cr"), 100.0),
                similar_works_count=int(_f(r.get("similar_works_count"), 27)),
                similar_work_pct=_f(r.get("similar_work_pct"), 40.0),
                scope_keywords=r.get("scope_keywords") or dict(_DEFAULT_SCOPE),
                include_keywords=r.get("include_keywords") or [],
                exclude_keywords=r.get("exclude_keywords") or list(_DEFAULT_EXCLUDE),
                turnover_last_year_cr=_f(r.get("turnover_last_year_cr"), 104.27),
                turnover_3yr_avg_cr=_f(r.get("turnover_3yr_avg_cr"), 103.79),
                net_worth_3yr_avg_cr=_f(r.get("net_worth_3yr_avg_cr"), 29.66),
                bank_solvency_cr=_f(r.get("bank_solvency_cr"), 30.65),
                gst_number=r.get("gst_number") or "",
                pan_number=r.get("pan_number") or "",
                certifications=r.get("certifications") or ["GST", "PAN", "ISO 9001", "EPF", "ESIC"],
                contractor_class=r.get("contractor_class"),
                can_form_jv=(r.get("can_form_jv") if r.get("can_form_jv") is not None else True),
                auto_reject_risks=r.get("auto_reject_risks") or "",
                no_go_locations=r.get("no_go_locations") or [],
                partial_margin_pct=_f(r.get("partial_margin_pct"), 5.0),
                partial_margins=r.get("partial_margins") or {},
                legal_items=r.get("legal_items") or [],
                analysis_instructions=r.get("analysis_instructions") or "",
            ), user_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("load_profile failed (%s) — using defaults", exc)
    return _attach_portfolio(Profile(), user_id)
