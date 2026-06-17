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
    "- 'find / fetch / get N tenders on <keyword>' (e.g. 'find 5 tenders on museum') means FETCH FRESH "
    "from TenderKart and process them → call run_fresh_scan(keyword='museum', limit=5). The pipeline runs "
    "in the background and posts a report (which are eligible / partial / rejected) when it finishes.\n"
    "- 'show / list / top tenders already found' → call search_tenders.\n"
    "- 'stop / cancel / kill the scan' → call stop_scan (halts the running background scan).\n"
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
    # reprocess=True so the matched tenders are (re)processed and reported even if
    # they were ingested by an earlier scan — the chat user wants a report on them.
    run_id = ingest.start_run(triggered_by="chat", filter_ids=fids, limit=n, reprocess=True)
    if run_id is None:
        return {"started": False, "message": "A scan is already running — its report will appear here when it finishes."}
    scope = f"'{keyword}'" if (keyword and fids) else "all sectors"
    return {"started": True, "run_id": run_id, "limit": n,
            "message": f"Scanning up to {n} {scope} tenders from TenderKart. "
                       "The report (which are eligible / partial / rejected) will appear here when the scan finishes."}


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
        return {"reply": "Sorry — I couldn't complete that. Try rephrasing."}
    except Exception as exc:  # noqa: BLE001
        log.exception("agent chat failed")
        return JSONResponse({"error": f"agent failed: {exc}"}, status_code=500)
