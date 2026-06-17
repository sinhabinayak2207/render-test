"""Deterministic field extraction from tender text — regex/NLP, NO LLM (free).

Fills the pattern-based fields (amounts, %, dates, contacts, award method).
Whatever it can't get is left out so the LLM fallback fills only those.
"""
from __future__ import annotations

import re

_AMOUNT = r"(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|million|mn)?"


def _to_cr(num: str, unit: str | None) -> float | None:
    try:
        n = float(num.replace(",", ""))
    except Exception:  # noqa: BLE001
        return None
    u = (unit or "").lower()
    if "lakh" in u or "lac" in u:
        return round(n / 100, 4)
    if "cr" in u:
        return round(n, 4)
    if "million" in u or u == "mn":
        return round(n / 10, 4)
    if n >= 100000:  # looks like raw rupees
        return round(n / 1e7, 4)
    return None  # ambiguous bare number → leave for the LLM


def _amount_near(text: str, anchor: str) -> float | None:
    m = re.search(anchor + r"[^.\n]{0,90}?" + _AMOUNT, text, re.I)
    return _to_cr(m.group(1), m.group(2)) if m else None


def _date_near(text: str, anchor: str) -> str | None:
    m = re.search(
        anchor + r"[^.\n]{0,60}?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        text, re.I,
    )
    if not m:
        return None
    try:
        from dateutil import parser as dp

        return dp.parse(m.group(1), dayfirst=True).date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def python_fields(text: str) -> dict:
    """Best-effort regex extraction. Keys absent when not confidently found."""
    t = text or ""
    out: dict = {}

    tov = _amount_near(t, r"(?:average\s+)?(?:annual\s+)?turnover")
    if tov is not None:
        out["min_turnover_cr"] = tov
    nw = _amount_near(t, r"net\s*worth")
    if nw is not None:
        out["min_networth_cr"] = nw

    m = re.search(r"(?:performance\s+(?:bank\s+)?guarantee|\bpbg\b|security\s+deposit)[^.\n]{0,40}?([\d.]+)\s*%", t, re.I)
    if m:
        try:
            out["pbg_percent"] = float(m.group(1))
        except Exception:  # noqa: BLE001
            pass

    m = re.search(r"(?:completion|project|contract)\s+(?:period|duration)[^.\n]{0,40}?(\d+)\s*(days?|months?|years?)", t, re.I)
    if m:
        out["project_duration"] = f"{m.group(1)} {m.group(2)}"

    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", t)
    phone = re.search(r"(?:\+91[-\s]?)?[6-9]\d{9}\b", t)
    contact = ", ".join(x.group(0) for x in (email, phone) if x)
    if contact:
        out["authority_contact"] = contact

    for k in ("QCBS", "LCS", "QBS", "least cost", "quality and cost", "L1"):
        if re.search(r"\b" + re.escape(k) + r"\b", t, re.I):
            out["award_method"] = k.upper() if len(k) <= 4 else k
            break

    val = (_amount_near(t, r"estimated\s+(?:project\s+)?(?:cost|value)")
           or _amount_near(t, r"(?:estimated\s+)?cost\s+put\s+to\s+(?:tender|bid)")
           or _amount_near(t, r"(?:tender|bid|contract)\s+value")
           or _amount_near(t, r"value\s+of\s+(?:work|the\s+work|contract)")
           or _amount_near(t, r"approx(?:imate)?\.?\s+(?:cost|value)"))
    if val is not None:
        out["estimated_value_cr"] = val

    pre = _date_near(t, r"pre[\s-]?bid")
    if pre:
        out["pre_bid_date"] = pre
    opn = _date_near(t, r"(?:technical\s+)?(?:bid\s+)?opening")
    if opn:
        out["opening_date"] = opn

    return out
