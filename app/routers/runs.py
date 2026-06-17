from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..auth import current_user
from ..pipeline import ingest

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("/trigger")
def trigger(
    triggered_by: str = Query("manual"),
    filter_ids: str | None = Query(None),
    user=Depends(current_user),
):
    ids = [s for s in (filter_ids.split(",") if filter_ids else []) if s.strip()] or None
    run_id = ingest.start_run(triggered_by=triggered_by, filter_ids=ids)
    if run_id is None:
        return JSONResponse({"error": "a cycle is already running"}, status_code=409)
    return {"run_id": run_id, "status": "queued"}


@router.post("/stop")
def stop(user=Depends(current_user)):
    active = ingest.request_stop()
    return {"stopped": active,
            "message": "Stopping the scan — the background process will halt shortly." if active
            else "No scan is running."}


@router.get("/status")
def status(user=Depends(current_user)):
    return ingest.latest_run_status()
