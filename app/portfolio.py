"""CS Direkt past-project portfolio (the experience evidence).

Stored in Supabase `company_portfolio` so it's editable and Claude/RULES can read it:
  - RULES uses it for SECTOR-WISE experience (largest similar work in the tender's
    category, not the overall max).
  - Claude references the matching projects in the narrative.

Source: '2) Credentials of CSDIREKT (Project wise Hashtags).docx'. The built-in
list below is the seed + fallback when the table is empty.
"""
from __future__ import annotations

import logging

from .supabase_client import service_client

log = logging.getLogger("portfolio")

# categories use the same names as Profile.scope_keywords keys.
PORTFOLIO: list[dict] = [
    {"project_name": "Jyotisar Museum, Kurukshetra", "client": "Haryana Tourism", "project_type": "Museum", "approx_value_cr": 100.0, "categories": ["Museums", "Heritage"]},
    {"project_name": "Chamkaur Sahib Museum", "client": "Punjab Heritage Board", "project_type": "Museum", "approx_value_cr": 28.0, "categories": ["Museums", "Heritage"]},
    {"project_name": "Valmik Museum, Amritsar", "client": "Punjab Heritage Board", "project_type": "Museum", "approx_value_cr": 26.0, "categories": ["Museums", "Heritage"]},
    {"project_name": "Rashtrapati Bhawan Sound & Light", "client": "ITDC", "project_type": "Sound & Light Show", "approx_value_cr": 21.0, "categories": ["Light & Sound"]},
    {"project_name": "Indian Museum Kolkata Renovation", "client": "Indian Museum Kolkata", "project_type": "Museum", "approx_value_cr": 20.0, "categories": ["Museums", "Heritage"]},
    {"project_name": "MPSTDC Mahakal, Ujjain (S&L + Water)", "client": "MP State Tourism", "project_type": "Sound & Light + Water", "approx_value_cr": 20.0, "categories": ["Light & Sound", "Content"]},
    {"project_name": "550th Guru Nanak Birth Celebration", "client": "Punjab Heritage Board", "project_type": "Multi-discipline Event", "approx_value_cr": 19.0, "categories": ["Events", "Content"]},
    {"project_name": "GAIL Experience Centre", "client": "GAIL India", "project_type": "Experience Centre / Projection Mapping", "approx_value_cr": 18.0, "categories": ["Tourism", "Content"]},
    {"project_name": "Lachit Museum", "client": "Assam Govt", "project_type": "Museum", "approx_value_cr": 15.0, "categories": ["Museums", "Heritage"]},
    {"project_name": "Kedarnath Parichay Museum", "client": "NCSM / DST", "project_type": "Museum / Interpretation Centre", "approx_value_cr": 15.0, "categories": ["Museums", "Tourism"]},
    {"project_name": "World Food India", "client": "FICCI", "project_type": "Exhibition + Event", "approx_value_cr": 12.0, "categories": ["Exhibitions", "MICE"]},
    {"project_name": "MPCST Planetarium, Ujjain", "client": "Ujjain Smart City", "project_type": "Planetarium / AV", "approx_value_cr": 8.0, "categories": ["Science Centres", "Content"]},
    {"project_name": "PM Museum Sound & Light", "client": "Nehru Memorial Museum", "project_type": "Sound & Light Show", "approx_value_cr": 8.0, "categories": ["Museums", "Light & Sound"]},
    {"project_name": "Suraj Kund Mela", "client": "Haryana Tourism", "project_type": "Event Festival", "approx_value_cr": 8.0, "categories": ["Events"]},
    {"project_name": "Dhordo Sound & Light Show", "client": "Gujarat Tourism", "project_type": "Sound & Light Show", "approx_value_cr": 7.0, "categories": ["Light & Sound"]},
    {"project_name": "Burhanpur Sound & Light Show", "client": "MP State Tourism", "project_type": "Sound & Light Show", "approx_value_cr": 5.0, "categories": ["Light & Sound"]},
    {"project_name": "Viraat Swaroop (Statue Mapping + S&L)", "client": "Haryana Tourism", "project_type": "Statue Mapping + S&L", "approx_value_cr": 5.0, "categories": ["Light & Sound"]},
    {"project_name": "Red Fort Projection Mapping", "client": "IGNCA", "project_type": "Projection Mapping", "approx_value_cr": 5.0, "categories": ["Content", "Light & Sound"]},
    {"project_name": "NFDC Film Bazaar", "client": "NFDC Goa", "project_type": "Exhibition", "approx_value_cr": 5.0, "categories": ["Exhibitions"]},
    {"project_name": "Sanchi Light & Sound", "client": "MP State Tourism", "project_type": "Sound & Light Show", "approx_value_cr": 4.5, "categories": ["Light & Sound"]},
    {"project_name": "Leh Sound & Light Show", "client": "ITDC", "project_type": "Sound & Light Show", "approx_value_cr": 4.0, "categories": ["Light & Sound"]},
    {"project_name": "Ajmer Smart City Cultural AV", "client": "Ajmer Smart City", "project_type": "Sound & Light Show", "approx_value_cr": 4.0, "categories": ["Light & Sound"]},
    {"project_name": "Navratri Festival", "client": "Gujarat Tourism", "project_type": "Event Festival", "approx_value_cr": 3.5, "categories": ["Events"]},
    {"project_name": "Pachmarhi Sound & Light Show", "client": "MP State Tourism", "project_type": "Sound & Light Show", "approx_value_cr": 3.0, "categories": ["Light & Sound"]},
    {"project_name": "Rose Garden Light & Sound", "client": "MCC Chandigarh", "project_type": "Sound & Light Show", "approx_value_cr": 2.0, "categories": ["Light & Sound"]},
    {"project_name": "APIIC Pavilion (CII Summit)", "client": "CII", "project_type": "Exhibition Pavilion", "approx_value_cr": 0.80, "categories": ["Exhibitions", "MICE"]},
    {"project_name": "GTB Kirtan Samagam", "client": "Punjab Heritage Board", "project_type": "Large Event / AV", "approx_value_cr": 0.30, "categories": ["Events"]},
]


def load_portfolio(user_id: str | None = None) -> list[dict]:
    """Portfolio rows from Supabase; falls back to the built-in list."""
    try:
        q = service_client().table("company_portfolio").select("*")
        q = q.eq("user_id", user_id) if user_id else q.is_("user_id", "null")
        res = q.execute()
        if res.data:
            return res.data
    except Exception as exc:  # noqa: BLE001
        log.warning("load_portfolio failed (%s) — using built-in", exc)
    return PORTFOLIO


def seed_portfolio() -> int:
    """Wipe + reinsert the default (user_id NULL) portfolio. Run once after table create."""
    c = service_client()
    c.table("company_portfolio").delete().is_("user_id", "null").execute()
    c.table("company_portfolio").insert(PORTFOLIO).execute()
    return len(PORTFOLIO)


def relevant_projects(portfolio: list[dict], categories, top_n: int = 4) -> list[dict]:
    """Projects whose categories intersect the tender's matched categories, by value."""
    cats = set(categories or [])
    rel = [p for p in (portfolio or []) if cats & set(p.get("categories") or [])]
    rel.sort(key=lambda p: p.get("approx_value_cr") or 0, reverse=True)
    return rel[:top_n]


def sector_largest(portfolio: list[dict], categories):
    """(value_cr, project_name, count) of the largest similar work in the matched sector.
    Falls back to the overall largest when no category matches."""
    rel = relevant_projects(portfolio, categories, top_n=1)
    cats = set(categories or [])
    cnt = len([p for p in (portfolio or []) if cats & set(p.get("categories") or [])])
    if rel:
        return rel[0].get("approx_value_cr") or 0, rel[0].get("project_name"), cnt
    if portfolio:
        top = max(portfolio, key=lambda p: p.get("approx_value_cr") or 0)
        return top.get("approx_value_cr") or 0, top.get("project_name"), len(portfolio)
    return None, None, 0


if __name__ == "__main__":  # python -m app.portfolio  → seed Supabase
    print("seeded portfolio rows:", seed_portfolio())
