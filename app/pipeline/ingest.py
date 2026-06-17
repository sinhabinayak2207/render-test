"""Ingest orchestrator: TenderKart -> extract -> RULES -> (narrate) -> Supabase.

Fills the EXISTING `tenders` table (TenderKart fields + regex/gpt-4o-mini extraction
+ deterministic RULES verdict) and `tender_artifacts` (one row per document).
Narrates live to `cycle_events`. Idempotent by tenderkart_id.

Run in background via /runs/trigger, or as CLI:  python -m app.pipeline.ingest
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timezone

from ..config import settings
from ..llm_extract import hybrid_extract
from ..narrative import generate_narrative
from ..profile import load_profile
from ..qualify import qualify, scope_check, title_excluded
from . import store
from .extract import ExtractResult, extract, vision_recover
from .tenderkart import TenderKart

log = logging.getLogger("ingest")

_lock = threading.Lock()
_active = False
_stop = threading.Event()   # set -> the running cycle halts after the current tender
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def request_stop() -> bool:
    """Stop the running cycle. If a live thread is processing, signal it to halt
    after the current tender; otherwise clear any stale 'running' lock in the DB.
    Returns True if something was running."""
    if _active:
        _stop.set()   # live cycle thread will halt + mark the run stopped
        return True
    if store.is_running():
        # No live cycle in this process — the lock is stale; clear it directly and
        # emit a done-progress so the live tracker hides (and stays hidden on reload).
        try:
            from ..supabase_client import service_client
            rows = service_client().table("tender_runs").select("id").eq("status", "running").execute().data or []
            service_client().table("tender_runs").update(
                {"status": "failed", "completed_at": _now()}
            ).eq("status", "running").execute()
            for r in rows:
                store.emit(r["id"], "warn", "🛑 Scan stopped — background process halted.",
                           meta={"progress": {"pct": 100, "label": "Stopped", "done": True}})
        except Exception as exc:  # noqa: BLE001
            log.warning("stale-lock clear failed: %s", exc)
        return True
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_part(iso: str | None) -> str | None:
    if not iso:
        return None
    return str(iso)[:10] if _DATE_RE.match(str(iso)[:10]) else None


def _valid_date(s) -> str | None:
    return s if isinstance(s, str) and _DATE_RE.match(s) else None


# ── public API used by the router ─────────────────────────────────────────────
def start_run(triggered_by: str = "manual", filter_ids: list[str] | None = None,
              limit: int | None = None, reprocess: bool | None = None) -> str | None:
    global _active
    with _lock:
        if _active or store.is_running():
            return None
        _active = True
    try:
        run_id = store.create_run(triggered_by)
    except Exception:
        with _lock:
            _active = False
        raise
    threading.Thread(target=_run_thread, args=(run_id, filter_ids, limit, reprocess), daemon=True).start()
    return run_id


def latest_run_status() -> dict:
    return store.latest_run()


def _run_thread(run_id: str, filter_ids: list[str] | None,
                limit: int | None = None, reprocess: bool | None = None) -> None:
    global _active
    try:
        run_cycle(run_id, filter_ids, limit, reprocess)
    except Exception as exc:  # noqa: BLE001
        log.exception("cycle crashed")
        store.emit(run_id, "error", f"Cycle failed: {exc}")
        store.update_run(run_id, status="failed", completed_at=_now())
    finally:
        with _lock:
            _active = False


# ── the cycle ─────────────────────────────────────────────────────────────────
def run_cycle(run_id: str, filter_ids: list[str] | None = None,
              limit: int | None = None, reprocess: bool | None = None) -> None:
    cap = int(limit) if limit else settings.max_tenders_per_run
    reproc = settings.reprocess_existing if reprocess is None else bool(reprocess)
    _stop.clear()
    tk = TenderKart()
    store.emit(run_id, "info", "Starting Tenderkart cycle…")
    if settings.upload_documents:
        store.ensure_bucket()
    prof = load_profile()  # editable RULES config (financials, scope keywords)

    filters = tk.list_filters()
    if filter_ids:
        wanted = set(filter_ids)
        filters = [f for f in filters if f["id"] in wanted]
    store.update_run(run_id, sites_total=len(filters))
    store.emit(run_id, "info", f"{len(filters)} filter(s) to scan since {settings.sync_updated_after}.")

    found = qualified = sites_done = 0
    stopped = False

    for f in filters:
        if _stop.is_set():
            stopped = True
            break
        fid = f["id"]
        fname = f.get("name") or fid
        store.emit(run_id, "info", f"Scanning filter: {fname}")
        f_count = 0
        try:
            for t in tk.iter_filter_tenders(fid, settings.sync_updated_after):
                if _stop.is_set():
                    stopped = True
                    break
                if found >= cap:
                    store.emit(run_id, "warn", "Reached the tender cap — stopping early.")
                    break
                tk_uuid = t["id"]
                # Below the ₹-floor (value disclosed) → reject outright, do NOT store.
                _val_cr = (t.get("tender_value") or 0) / 1e7
                if _val_cr and _val_cr < prof.min_tender_value_cr:
                    store.emit(run_id, "info", f"Skipped (below ₹{prof.min_tender_value_cr} Cr floor): {(t.get('title') or '')[:40]}")
                    continue
                if not reproc and store.tender_db_id(tk_uuid):
                    continue  # already ingested — idempotent skip
                try:
                    verdict = _ingest_tender(tk, tk_uuid, fname, run_id, prof)
                except Exception as exc:  # noqa: BLE001 — one tender must not abort the filter
                    log.warning("tender %s failed: %s", tk_uuid, exc)
                    store.emit(run_id, "warn", f"Skipped a tender ({tk_uuid[:8]}): {exc}")
                    continue
                found += 1
                f_count += 1
                if _stop.is_set():   # stopped mid-tender → don't emit a stray progress tick
                    stopped = True
                    break
                _cap = cap
                store.emit(run_id, "info", f"Processing tenders {found}/{_cap}",
                           meta={"progress": {"pct": round(found / max(_cap, 1) * 88),
                                              "label": f"Processing tenders ({found}/{_cap})",
                                              "processed": found, "total": _cap}})
                if verdict in ("ELIGIBLE", "PARTIAL"):
                    qualified += 1
            sites_done += 1
            store.emit(run_id, "success", f"{fname}: {f_count} new tenders processed.")
        except Exception as exc:  # noqa: BLE001 — one bad filter shouldn't kill the run
            log.exception("filter %s failed", fname)
            store.emit(run_id, "error", f"{fname} failed: {exc}")
        store.update_run(
            run_id, sites_succeeded=sites_done, sites_failed=len(filters) - sites_done,
            tenders_found=found, tenders_qualified=qualified,
        )
        if stopped:
            break

    if stopped:
        store.emit(run_id, "warn", "🛑 Scan stopped — background process halted.",
                   meta={"progress": {"pct": 100, "label": "Stopped", "done": True}})
        store.update_run(run_id, status="failed", completed_at=_now(),
                         tenders_found=found, tenders_qualified=qualified, sites_succeeded=sites_done)
        return

    # Final phase — generate the PDF report, upload it, and post it (with download link) to the chat.
    store.emit(run_id, "info", "Generating report…",
               meta={"progress": {"pct": 92, "label": "Generating report…"}})
    report_url = None
    try:
        import os
        import tempfile

        from ..report_pdf import build_pdf
        out = os.path.join(tempfile.gettempdir(), f"tender_report_{run_id[:8]}.pdf")
        build_pdf(run_id, out_path=out)   # WeasyPrint, with a reportlab fallback on Windows
        with open(out, "rb") as fh:
            report_url = store.upload_report(run_id, fh.read())
    except Exception as exc:  # noqa: BLE001
        log.warning("report generation/upload failed: %s", exc)

    # In-chat report — verdict breakdown + the PDF download link (rendered in the dashboard chat).
    try:
        from ..supabase_client import service_client
        rows = (service_client().table("tenders")
                .select("title,verdict,competitiveness_score").eq("run_id", run_id)
                .neq("verdict", "EXCLUDED").order("competitiveness_score", desc=True).execute().data or [])
        buckets: dict[str, list] = {"ELIGIBLE": [], "PARTIAL": [], "INELIGIBLE": []}
        for r in rows:
            buckets.setdefault(r.get("verdict"), buckets["INELIGIBLE"]).append(r)
        lines = [f"📋 Report — {len(rows)} tenders: {len(buckets['ELIGIBLE'])} eligible · "
                 f"{len(buckets['PARTIAL'])} partially eligible · {len(buckets['INELIGIBLE'])} rejected"]
        for label, key in (("ELIGIBLE", "ELIGIBLE"), ("PARTIAL", "PARTIAL"), ("REJECTED", "INELIGIBLE")):
            for r in buckets.get(key, []):
                lines.append(f"• [{label}] {(r.get('title') or '')[:70]} ({r.get('competitiveness_score')}/100)")
        meta = {"report": True, "is_chat_reply": True}
        if report_url:
            lines.append("\nDownload the full PDF report below.")
            meta["combined_url"] = report_url
            meta["combined_name"] = "Tender Intelligence Report"
        store.emit(run_id, "success", "\n".join(lines), meta=meta)
    except Exception as exc:  # noqa: BLE001
        log.warning("report summary failed: %s", exc)

    store.update_run(
        run_id, status="completed", completed_at=_now(),
        tenders_found=found, tenders_qualified=qualified, sites_succeeded=sites_done,
    )
    store.emit(run_id, "success", f"Cycle complete — {found} tenders processed, {qualified} qualified.",
               meta={"progress": {"pct": 100, "label": "Done", "done": True}})


def _ingest_tender(tk: TenderKart, tk_uuid: str, filter_name: str, run_id: str, profile) -> str:
    detail = tk.get_tender(tk_uuid)

    # COST GATE — cheap scope check on the summary; if clearly out of scope, skip
    # the expensive document download + extraction + LLM entirely.
    pre_text = " ".join(str(detail.get(k) or "") for k in ("title", "tender_category", "product_category", "organisation"))
    pre_excluded = scope_check(pre_text, profile)["excluded"] or title_excluded(str(detail.get("title") or ""), profile)

    # STEP 1 — "Ctrl+A": copy all selectable text from every document.
    extracted, hashes = [], []
    if pre_excluded:
        store.emit(run_id, "info", f"Out of scope — skipped extraction: {(detail.get('title') or '')[:42]}")
    for doc in (detail.get("documents", []) if not pre_excluded else []):
        doc_id = doc.get("id")
        name = doc.get("name", doc_id or "document")
        try:
            content = tk.download_document(doc_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("doc download %s failed: %s", name, exc)
            continue
        url = store.upload_document(tk_uuid, doc_id, name, content) if settings.upload_documents else None
        res = extract(name, content)  # selectable text only (no OCR here)
        extracted.append({"doc": doc, "name": name, "content": content, "res": res, "url": url})
        hashes.append(res.content_hash)

    combined = []
    for e in extracted:
        pages = e["res"].pages or [e["res"].markdown]
        for pno, ptext in enumerate(pages, 1):
            if ptext and ptext.strip():
                combined.append(f"\n\n=== DOCUMENT: {e['name']} | PAGE {pno} ===\n{ptext}")
    combined_md = "\n".join(combined).strip()

    # STEP 2 — only if the text copy came back essentially empty, call gpt-4o-mini vision.
    vision_text: dict[str, str] = {}
    if len(combined_md) < 300 and settings.enable_vision_fallback:
        store.emit(run_id, "info", "Text copy empty — falling back to gpt-4o-mini vision…")
        for e in extracted:
            vmd = vision_recover(e["name"], e["content"])
            if vmd:
                vision_text[e["doc"].get("id")] = vmd
                combined.append(f"\n\n=== DOCUMENT: {e['name']} (vision) ===\n{vmd}")
        combined_md = "\n".join(combined).strip()

    artifacts, docs_meta = [], []
    for e in extracted:
        did = e["doc"].get("id")
        text = vision_text.get(did) or e["res"].markdown
        artifacts.append(
            {"file_name": e["name"], "file_type": e["res"].fmt, "storage_url": e["url"], "extracted_text": text}
        )
        docs_meta.append(
            {"doc_id": did, "name": e["name"], "kind": e["doc"].get("document_type"),
             "format": e["res"].fmt, "pages": len(e["res"].pages or [e["res"].markdown]),
             "storage_url": e["url"], "public_url": e["url"], "ocr_used": did in vision_text}
        )

    # 2) EXTRACT — hybrid: Python/regex (free) first, gpt-4o-mini ONLY for missed fields.
    ex: dict = {}
    ex_log: dict = {}
    if combined_md and not pre_excluded:
        ex, ex_log = hybrid_extract(combined_md)

    content_hash = hashlib.sha256(
        (json.dumps(detail, sort_keys=True, default=str) + "".join(hashes)).encode()
    ).hexdigest()

    # 3) build the tenders row. TK + Py + EXTRACT fields now; verdict/score/risk
    #    (RULES) and narrative (Claude) layers are filled later.
    row = {
        "run_id": run_id,
        "tenderkart_id": tk_uuid,
        "content_hash": content_hash,
        "portal_name": detail.get("portal_name") or "tenderkart",
        "title": detail.get("title") or "(untitled)",
        "reference_number": detail.get("tender_reference_number"),
        "issuing_authority": detail.get("organisation"),
        "issuing_authority_location": ex.get("issuing_authority_location"),
        "authority_contact": ex.get("authority_contact"),
        # TenderKart value first; if it didn't disclose one, use the value the
        # extractor pulled from the BOQ/RFP (regex → gpt-4o-mini), Cr → INR.
        "estimated_value": detail.get("tender_value") or (round(ex["estimated_value_cr"] * 1e7) if ex.get("estimated_value_cr") else None),
        "emd_amount": detail.get("emd_fee"),
        "emd_currency": "INR",
        "pbg_percent": ex.get("pbg_percent"),
        "min_turnover_cr": ex.get("min_turnover_cr"),
        "min_networth_cr": ex.get("min_networth_cr"),
        "pre_bid_date": _valid_date(ex.get("pre_bid_date")),
        "opening_date": _valid_date(ex.get("opening_date")),
        "closing_date": _date_part(detail.get("closing_at")),
        "published_at": detail.get("published_at"),
        "tender_type": ex.get("award_method"),       # EXTRACT (L1/QCBS/…)
        "tender_mode": detail.get("tender_type"),     # TK (Open/Limited)
        "procurement_model": ex.get("procurement_model"),    # EPC / O&M / PPP …
        "commercial_model": ex.get("commercial_model"),      # who pays whom
        "scope_summary": ex.get("scope_summary"),
        "location_of_execution": ex.get("location_of_execution"),
        "project_duration": ex.get("project_duration"),
        "source_url": f"tenderkart://{detail.get('portal_name')}/{detail.get('tender_id')}",
        "raw_text": combined_md[:200000],
        "verdict": "PENDING",                         # RULES layer (later)
        "matched_keyword": filter_name,
        "matched_bucket": filter_name,
        "matched_categories": [c for c in (detail.get("tender_category"), detail.get("product_category")) if c],
        "key_deliverables": ex.get("key_deliverables"),
        "eligibility_conditions": ex.get("eligibility_conditions"),
        "unusual_clauses": ex.get("unusual_clauses"),
        "penalty_clauses": ex.get("penalty_clauses"),
        "sow_page_refs": ex.get("sow_page_refs"),
        "downloaded_docs": docs_meta,
        "extracted_data": {
            "all_fields": ex.get("all_fields"),
            "key_dates": ex.get("key_dates"),
            "extras": ex.get("extras"),
            "tender_type_confidence": ex.get("tender_type_confidence"),
            "tender_type_basis": ex.get("tender_type_basis"),
            "commercial_basis": ex.get("commercial_basis"),
            "similar_work_pct": ex.get("similar_work_pct"),
            "similar_work_required_cr": ex.get("similar_work_required_cr"),
            "tenderkart": detail,
        },
        "extraction_log": ex_log,
        # narrative columns reset to null on every run; the narrate step fills the
        # relevant ones — prevents stale prose when a verdict changes.
        "narrative_fit": None, "key_business_insight": None, "strategic_fit_basis": None,
        "compliance_basis": None, "risk_layperson_explanation": None, "pre_bid_queries": None,
        "disqualification_triggers": None, "business_logic_explanation": None,
    }
    # 4) RULES — deterministic verdict / score / risk (NO LLM)
    row.update(qualify(row, profile))

    # 5) NARRATE — Claude writes the report prose (skip clearly out-of-scope EXCLUDED)
    if settings.anthropic_api_key and row.get("verdict") != "EXCLUDED":
        try:
            row.update(generate_narrative(row, profile))
        except Exception as exc:  # noqa: BLE001
            log.warning("narrative failed: %s", exc)

    tender_id = store.upsert_tender(row, tk_uuid)
    store.replace_artifacts(tender_id, artifacts)
    log.info("saved: %s | %s score=%s | docs=%d | fields=%d",
             (detail.get("title") or "")[:40], row["verdict"], row.get("competitiveness_score"),
             len(artifacts), len(ex.get("all_fields") or []))
    return row["verdict"]


# ── CLI entrypoint (cron / manual) ─────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    for _noisy in ("httpx", "httpcore", "paddle", "paddlex", "paddleocr", "PIL"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    rid = store.create_run("scheduled")
    print(f"run_id={rid}")
    try:
        run_cycle(rid)
    except Exception as e:  # noqa: BLE001
        store.emit(rid, "error", f"Cycle failed: {e}")
        store.update_run(rid, status="failed", completed_at=_now())
        raise
