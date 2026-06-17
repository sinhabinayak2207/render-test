"""TenderKart Client API wrapper.

Auth: header `X-API-Key`. The API rate-limits aggressively (429), so every call
goes through tenacity backoff plus a configurable inter-request delay.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import settings

log = logging.getLogger("tenderkart")


class RateLimited(Exception):
    pass


class TenderKart:
    def __init__(self) -> None:
        self.base = settings.tenderkart_base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {"X-API-Key": settings.tenderkart_api_key, "Accept": "application/json"}
        )
        self.delay = settings.request_delay_seconds

    @retry(
        retry=retry_if_exception_type(RateLimited),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _get(self, path: str, params: dict | None = None, raw: bool = False):
        time.sleep(self.delay)  # be polite to the rate limiter
        resp = self.session.get(f"{self.base}{path}", params=params, timeout=90)
        if resp.status_code == 429:
            log.warning("429 from %s — backing off", path)
            raise RateLimited(path)
        resp.raise_for_status()
        return resp.content if raw else resp.json()

    # ── endpoints ────────────────────────────────────────────────────────────
    def list_filters(self) -> list[dict]:
        return self._get("/filters").get("filters", [])

    def iter_filter_tenders(
        self, filter_id: str, updated_after: str, status: str = "active"
    ) -> Iterator[dict]:
        """Yield tender summaries for a filter, following cursor pagination."""
        cursor: str | None = None
        first = True
        while True:
            if cursor:
                params: dict[str, Any] = {"cursor": cursor, "limit": 100}
            else:
                params = {"updated_after": updated_after, "status": status, "limit": 100}
            data = self._get(f"/filters/{filter_id}/tenders", params=params)
            for t in data.get("tenders", []):
                yield t
            pag = data.get("pagination", {})
            if pag.get("has_more") and pag.get("next_cursor"):
                cursor = pag["next_cursor"]
                first = False
            else:
                break

    def get_tender(self, tender_uuid: str) -> dict:
        return self._get(f"/tenders/{tender_uuid}")

    def download_document(self, doc_id: str) -> bytes:
        return self._get(f"/documents/{doc_id}", raw=True)
