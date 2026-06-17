"""Company profile (editable RULES config) — read/update the Supabase row the
qualifier uses. Single shared profile for now (user_id IS NULL); multi-tenant
per-user later. Writes use the service key.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import current_user
from ..keywords import generate_keywords
from ..supabase_client import service_client

router = APIRouter(prefix="/profile", tags=["profile"])

_EDITABLE = {
    "company_name", "turnover_3yr_avg_cr", "turnover_5yr_avg_cr", "turnover_latest_cr",
    "turnover_last_year_cr", "net_worth_latest_cr", "net_worth_avg_cr", "net_worth_3yr_avg_cr",
    "solvency_cert_cr", "bank_solvency_cr",
    "min_tender_value_cr", "max_tender_value_cr", "emd_threshold_cr", "pbg_threshold_pct",
    "eligible_min_score", "partial_min_score",
    "scope_description", "service_lines", "scope_keywords", "include_keywords", "exclude_keywords",
    "gst_number", "pan_number", "certifications", "contractor_class", "can_form_jv",
    "auto_reject_risks", "no_go_locations", "partial_margin_pct", "partial_margins", "legal_items",
    "analysis_instructions",
}


def _default_row():
    res = service_client().table("company_profiles").select("*").is_("user_id", "null").limit(1).execute()
    return res.data[0] if res.data else None


@router.get("")
def get_profile(user=Depends(current_user)):
    return _default_row() or {}


@router.put("")
def put_profile(body: dict, user=Depends(current_user)):
    patch = {k: v for k, v in body.items() if k in _EDITABLE}
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    row = _default_row()
    if row:
        service_client().table("company_profiles").update(patch).eq("id", row["id"]).execute()
    else:
        service_client().table("company_profiles").insert({**patch, "user_id": None}).execute()
    return _default_row() or {}


@router.post("/generate-keywords")
def generate_keywords_route(user=Depends(current_user)):
    """One-time Claude call: scope_description → include/exclude/scope keywords → Supabase."""
    row = _default_row() or {}
    desc = row.get("scope_description") or ""
    if not desc.strip():
        return JSONResponse({"error": "Add a scope description first, then generate."}, status_code=400)
    kw = generate_keywords(desc)
    if not kw:
        return JSONResponse({"error": "Keyword generation unavailable — set ANTHROPIC_API_KEY."}, status_code=503)
    patch = {k: kw[k] for k in ("service_lines", "scope_keywords", "include_keywords", "exclude_keywords")}
    patch["keywords_generated_at"] = datetime.now(timezone.utc).isoformat()
    if row:
        service_client().table("company_profiles").update(patch).eq("id", row["id"]).execute()
    return _default_row() or {}


_PF_COLS = ("project_name", "client", "project_type", "approx_value_cr", "categories",
            "description", "completion_certificate")


@router.get("/portfolio")
def get_portfolio(user=Depends(current_user)):
    res = (service_client().table("company_portfolio").select("*")
           .is_("user_id", "null").order("approx_value_cr", desc=True).execute())
    return {"items": res.data or []}


@router.put("/portfolio")
def put_portfolio(body: dict, user=Depends(current_user)):
    """Replace the default (user_id NULL) portfolio with the posted items."""
    rows = []
    for it in (body.get("items") or []):
        if not str(it.get("project_name") or "").strip():
            continue
        row = {k: it[k] for k in _PF_COLS if k in it}
        row["user_id"] = None
        rows.append(row)
    c = service_client()
    c.table("company_portfolio").delete().is_("user_id", "null").execute()
    if rows:
        c.table("company_portfolio").insert(rows).execute()
    res = c.table("company_portfolio").select("*").is_("user_id", "null").order("approx_value_cr", desc=True).execute()
    return {"items": res.data or []}
