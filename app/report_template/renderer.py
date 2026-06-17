"""Jinja2 + WeasyPrint HTML→PDF renderer.

Loads templates from `templates/`. Embeds shared CSS from `static/style.css`
so WeasyPrint produces a single self-contained PDF with no external asset
fetches.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

# macOS local dev: WeasyPrint's cairo/pango/gobject dylibs live in /opt/homebrew/lib
# (brew install pango). ctypes.util.find_library() won't find them without help.
# Linux/Docker rely on apt-installed libs at standard paths — no shim needed.
if sys.platform == "darwin":
    _brew_lib = "/opt/homebrew/lib"
    if Path(_brew_lib).is_dir():
        _cur = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        if _brew_lib not in _cur.split(":"):
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                f"{_brew_lib}:{_cur}" if _cur else _brew_lib
            )

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402
from weasyprint import CSS, HTML  # noqa: E402

_DIR = Path(__file__).resolve().parent
_TEMPLATES = _DIR / "templates"
_STATIC = _DIR / "static"


@lru_cache(maxsize=1)
def _env() -> Environment:
    # Autoescape on for html/xml — every templated variable goes through
    # MarkupSafe escape. Templates render to a server-side PDF via WeasyPrint;
    # the HTML string is never returned to a browser. Templates must never
    # apply `|safe` to user-controlled fields (tender title, scope, etc).
    env = Environment(  # nosemgrep: direct-use-of-jinja2
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["money_cr"] = _money_cr
    env.filters["isoday"] = _isoday
    env.filters["nz"] = _nz
    env.filters["pct"] = lambda v: f"{float(v):.0f}%" if v is not None else "—"
    return env


def _money_cr(v: float | None) -> str:
    if v is None:
        return "—"
    try:
        return f"Rs. {float(v):.2f} Cr"
    except (TypeError, ValueError):
        return "—"


def _isoday(d: date | datetime | str | None) -> str:
    if d is None:
        return "—"
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def _nz(v: Any, fallback: str = "—") -> str:
    if v is None:
        return fallback
    if isinstance(v, str) and not v.strip():
        return fallback
    return str(v)


def _css() -> CSS:
    return CSS(filename=str(_STATIC / "style.css"))


def render_to_pdf(
    *, template: str, context: dict[str, Any], out_path: Path,
) -> Path:
    """Render `template` with `context` and write a PDF to `out_path`."""
    html_str = _env().get_template(template).render(**context)
    HTML(string=html_str, base_url=str(_STATIC)).write_pdf(
        target=str(out_path), stylesheets=[_css()],
    )
    return out_path


__all__ = ["render_to_pdf"]
