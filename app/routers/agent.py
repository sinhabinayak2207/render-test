"""Chat agent — orchestrates the tender pipeline via natural language (gpt-5-mini).

Tools the model can call:
  • search_tenders(keyword, limit, status) — query stored tenders (the DB)
  • run_fresh_scan(limit, keyword)         — start a fresh TenderKart scan

POST /agent/chat  {message, history:[{role,content}]} -> {reply}
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import current_user
from ..config import settings
from ..pipeline import ingest
from ..supabase_client import service_client

log = logging.getLogger("agent")
router = APIRouter(prefix="/agent", tags=["agent"])

_SYSTEM = (
    "You are CS Direkt's tender assistant. You orchestrate the pipeline.\n"
    "- ANY 'find / fetch / get / search N tenders on <keyword>' (e.g. 'find 5 tenders on museum') means "
    "FETCH LIVE FROM THE TENDERKART API — ALWAYS call run_fresh_scan(keyword='museum', limit=5). This NEVER "
    "reads from the database; it pulls fresh from TenderKart and re-processes (duplicates are fine). The "
    "pipeline runs in the background and posts a report (eligible / partial / rejected) when it finishes.\n"
    "- 'find N tenders across multiple keywords / all sectors / auto / pick for me' → call "
    "run_fresh_scan(limit=N) with NO keyword (scans ALL of CS Direkt's sectors in one run). Do NOT ask the "
    "user to list keywords and do NOT invent unrelated keywords (e.g. catering, security, logistics) — CS "
    "Direkt's sectors are fixed (museums, light & sound, events, exhibitions, science centres, heritage, "
    "tourism, content). Just start the scan. Prefer to ACT; only ask a clarifying question if truly ambiguous.\n"
    "- ONLY call search_tenders if the user EXPLICITLY says 'already found' / 'in the database' / 'stored' / "
    "'previously processed'. Never use it for a plain 'find ... tenders' request.\n"
    "- 'stop / cancel / kill the scan' → call stop_scan (halts the running background scan).\n"
    "- 'report do' / 'show me the report' / 'report for the last tenders' → call generate_report "
    "(posts the verdict breakdown + PDF download link to the chat).\n"
    "After run_fresh_scan returns, tell the user the scan started and the report will appear here when done. "
    "After search_tenders, list each as '<title> — <authority> — <value> — <verdict> (<score>/100)'. "
    "Never invent tenders; only use tool results."
)

_TOOLS = [
    {"type": "function", "function": {
        "name": "run_fresh_scan",
        "description": "Fetch NEW tenders from TenderKart for a keyword/sector and process them (extract + verdict + report). Use for 'find/fetch/get N tenders on <keyword>'.",
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string", "description": "sector/keyword, e.g. museum, light and sound, heritage; omit for all sectors"},
            "limit": {"type": "integer", "description": "how many tenders to fetch & process"},
        }}}},
    {"type": "function", "function": {
        "name": "search_tenders",
        "description": "Search tenders ALREADY stored/processed in the database by keyword/sector. Use for show/list/top of existing results (no fresh fetch).",
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string", "description": "sector or keyword; '' for all"},
            "limit": {"type": "integer"},
            "status": {"type": "string", "enum": ["ELIGIBLE", "PARTIAL", "INELIGIBLE", "any"]},
        }, "required": ["keyword"]}}},
    {"type": "function", "function": {
        "name": "stop_scan",
        "description": "Stop / cancel the currently running scan — halts the background process.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "generate_report",
        "description": "Build & post the PDF report (verdict breakdown + download link) for the most recent run's tenders. Use for 'report do' / 'show me the report' / 'report for the last tenders'.",
        "parameters": {"type": "object", "properties": {}}}},
]


def _money(inr) -> str:
    if not inr:
        return "value not disclosed"
    cr = inr / 1e7
    return f"Rs. {cr:.2f} Cr" if cr >= 0.01 else "value not disclosed"


def _search_tenders(keyword: str, limit: int = 10, status: str = "any") -> dict:
    q = (service_client().table("tenders")
         .select("title,issuing_authority,estimated_value,verdict,competitiveness_score,matched_categories,scope_summary,closing_date")
         .neq("verdict", "EXCLUDED").order("competitiveness_score", desc=True).limit(300))
    if status and status != "any":
        q = q.eq("verdict", status)
    rows = q.execute().data or []
    kw = (keyword or "").strip().lower()
    if kw:
        rows = [r for r in rows if kw in (r.get("title") or "").lower()
                or kw in (r.get("scope_summary") or "").lower()
                or any(kw in (c or "").lower() for c in (r.get("matched_categories") or []))]
    out = [{
        "title": r.get("title"), "authority": r.get("issuing_authority"),
        "value": _money(r.get("estimated_value")), "verdict": r.get("verdict"),
        "score": r.get("competitiveness_score"), "closing_date": r.get("closing_date"),
    } for r in rows[: max(1, int(limit or 10))]]
    return {"count": len(out), "tenders": out}


def _run_fresh_scan(keyword: str | None = None, limit: int | None = None) -> dict:
    n = max(1, int(limit)) if limit else settings.max_tenders_per_run
    fids = None
    if keyword and keyword.strip():
        try:
            from ..pipeline.tenderkart import TenderKart
            kw = keyword.strip().lower()
            fids = [f["id"] for f in TenderKart().list_filters() if kw in (f.get("name") or "").lower()] or None
        except Exception as exc:  # noqa: BLE001
            log.warning("filter resolve failed: %s", exc)
    # reprocess=False: a tender is processed ONCE and its verdict is locked. Re-running
    # must NOT re-extract the same tender (the LLM returns slightly different numbers each
    # time, which flips ELIGIBLE/PARTIAL/REJECTED) — already-ingested tenders are skipped,
    # so each scan only processes genuinely NEW tenders.
    run_id = ingest.start_run(triggered_by="chat", filter_ids=fids, limit=n, reprocess=False)
    if run_id is None:
        return {"started": False, "message": "A scan is already running — its report will appear here when it finishes."}
    scope = f"'{keyword}'" if (keyword and fids) else "all sectors"
    return {"started": True, "run_id": run_id, "limit": n,
            "message": f"Scanning up to {n} {scope} tenders from TenderKart. "
                       "The report (which are eligible / partial / rejected) will appear here when the scan finishes."}


def _generate_report() -> dict:
    """Build the PDF report for the most recent run that has tenders, upload it, and post it
    (verdict breakdown + download link) to the chat. Works for stopped/completed runs alike."""
    import os
    import tempfile

    from ..pipeline import store
    from ..report_pdf import build_pdf

    runs = (service_client().table("tender_runs").select("id")
            .order("started_at", desc=True).limit(20).execute().data or [])
    rid = None
    for r in runs:
        has = (service_client().table("tenders").select("id").eq("run_id", r["id"])
               .neq("verdict", "EXCLUDED").limit(1).execute().data or [])
        if has:
            rid = r["id"]
            break
    if not rid:
        return {"ok": False, "message": "No processed tenders found yet — run a scan first."}

    out = os.path.join(tempfile.gettempdir(), f"tender_report_{rid[:8]}.pdf")
    build_pdf(rid, out_path=out)
    with open(out, "rb") as fh:
        url = store.upload_report(rid, fh.read())
    rows = (service_client().table("tenders").select("title,verdict,competitiveness_score")
            .eq("run_id", rid).neq("verdict", "EXCLUDED").order("competitiveness_score", desc=True).execute().data or [])
    b = {"ELIGIBLE": [], "PARTIAL": [], "INELIGIBLE": []}
    for r in rows:
        # Only bucket KNOWN verdicts — setdefault folded None/'PENDING' into INELIGIBLE,
        # over-reporting the rejected count with tenders that were never evaluated.
        if r.get("verdict") in b:
            b[r["verdict"]].append(r)
    lines = [f"📋 Report — {len(rows)} tenders: {len(b['ELIGIBLE'])} eligible · "
             f"{len(b['PARTIAL'])} partially eligible · {len(b['INELIGIBLE'])} rejected"]
    for lab, k in (("ELIGIBLE", "ELIGIBLE"), ("PARTIAL", "PARTIAL"), ("REJECTED", "INELIGIBLE")):
        for r in b.get(k, []):
            lines.append(f"• [{lab}] {(r.get('title') or '')[:70]} ({r.get('competitiveness_score')}/100)")
    meta = {"report": True, "is_chat_reply": True}
    if url:
        lines.append("\nDownload the full PDF report below.")
        meta["combined_url"] = url
        meta["combined_name"] = "Tender Intelligence Report"
    store.emit(rid, "success", "\n".join(lines), meta=meta)
    return {"ok": True, "message": f"Posted the report for {len(rows)} tenders above (with PDF download link)."}


def _dispatch(name: str, args: dict) -> dict:
    try:
        if name == "search_tenders":
            return _search_tenders(args.get("keyword", ""), int(args.get("limit") or 10), args.get("status", "any"))
        if name == "run_fresh_scan":
            return _run_fresh_scan(args.get("keyword"), args.get("limit"))
        if name == "stop_scan":
            active = ingest.request_stop()
            return {"stopped": active,
                    "message": "Stopping the scan — background process halting." if active else "No scan is running."}
        if name == "generate_report":
            return _generate_report()
    except Exception as exc:  # noqa: BLE001
        log.warning("tool %s failed: %s", name, exc)
        return {"error": str(exc)}
    return {"error": "unknown tool"}


@router.post("/chat")
def chat(body: dict, user=Depends(current_user)):
    if not settings.openai_api_key:
        return JSONResponse({"error": "OPENAI_API_KEY not set"}, status_code=503)
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)
    history = body.get("history") or []
    msgs = [{"role": "system", "content": _SYSTEM}]
    for h in history[-6:]:
        role = "assistant" if h.get("role") == "agent" else "user"
        if h.get("content"):
            msgs.append({"role": role, "content": str(h["content"])})
    msgs.append({"role": "user", "content": message})

    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        for _ in range(4):
            resp = client.chat.completions.create(
                model=settings.openai_chat_model, messages=msgs, tools=_TOOLS,
            )
            m = resp.choices[0].message
            if not m.tool_calls:
                return {"reply": m.content or "—"}
            msgs.append({"role": "assistant", "content": m.content or "",
                         "tool_calls": [{"id": tc.id, "type": "function",
                                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                        for tc in m.tool_calls]})
            for tc in m.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                result = _dispatch(tc.function.name, args)
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)})
        return {"reply": "Started what I could. Say 'show me the report' once a scan finishes, "
                         "or rephrase your request."}
    except Exception as exc:  # noqa: BLE001
        log.exception("agent chat failed")
        # Always return a reply (200) so the chat shows the real error, never a bare "Agent error: OK".
        return {"reply": f"⚠️ I hit an error: {exc}. Try again, or rephrase the request."}
