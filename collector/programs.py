"""Watch big-bank campus program pages (full-time analyst programs are often one evergreen
page rather than a job posting). Each run: fetch, reduce to visible text, look for
open/closed wording, and note when the page changed since the last run."""
from __future__ import annotations

import hashlib
import re

from .util import session, strip_html

OPEN = re.compile(r"(applications? (are|is) (now )?open|now accepting|apply now|accepting applications|apply today)", re.I)
CLOSED = re.compile(r"(applications? (are|have|has) (now )?closed|no longer accepting|not currently accepting|"
                    r"applications? will open|check back|opens? in (january|february|march|april|may|june|july|august|september|october|november|december))", re.I)


def check(pages: list[dict], prev: dict) -> dict:
    out = {}
    for p in pages:
        key = p["name"]
        try:
            r = session().get(p["url"], timeout=25)
            r.raise_for_status()
            html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", r.text)
            text = re.sub(r"\s+", " ", strip_html(html))
            h = hashlib.sha1(text.encode()).hexdigest()[:12]
            status = "closed" if CLOSED.search(text) else ("open" if OPEN.search(text) else "unclear")
            old = prev.get(key) or {}
            out[key] = {"company": p.get("company", ""), "url": p["url"], "status": status, "hash": h,
                        "changed": bool(old) and old.get("hash") != h,
                        "status_changed": bool(old) and old.get("status") != status,
                        "chars": len(text), "ok": True,
                        "snippet": (CLOSED.search(text) or OPEN.search(text) or [""])[0] if status != "unclear" else ""}
        except Exception as e:
            out[key] = {**(prev.get(key) or {}), "ok": False, "error": str(e)[:150], "url": p["url"]}
    return out
