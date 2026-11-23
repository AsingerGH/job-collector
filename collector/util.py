"""Small shared helpers: HTTP session, HTML stripping, date parsing, ids."""
from __future__ import annotations

import hashlib
import html
import re
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})
        _session = s
    return _session


def get_json(url: str, *, params=None, timeout=25, retries=2):
    return _request("GET", url, params=params, timeout=timeout, retries=retries)


def post_json(url: str, payload: dict, *, timeout=25, retries=2):
    return _request("POST", url, json=payload, timeout=timeout, retries=retries)


def _request(method, url, *, retries=2, **kw):
    last = None
    for attempt in range(retries + 1):
        try:
            r = session().request(method, url, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"HTTP {r.status_code} for {url}")
                wait = r.headers.get("Retry-After")
                time.sleep(min(60, int(wait)) if wait and wait.isdigit() else (8 * (attempt + 1) if r.status_code == 429 else 2 * (attempt + 1)))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:  # ValueError = bad JSON
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{method} {url} failed: {last}")


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def strip_html(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(html.unescape(s))  # Greenhouse double-escapes content
    s = re.sub(r"<(br|/p|/li|/h\d|/div)\s*/?>", "\n", s, flags=re.I)
    s = _TAG.sub(" ", s)
    s = _WS.sub(" ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def today() -> date:
    return datetime.now(timezone.utc).astimezone().date()


def parse_date(v) -> str | None:
    """Return ISO yyyy-mm-dd from many formats (epoch ms, ISO strings, Workday 'Posted 3 Days Ago')."""
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, (int, float)):
        ts = v / 1000 if v > 1e11 else v
        return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    low = s.lower()
    if "today" in low or "just posted" in low:
        return today().isoformat()
    if "yesterday" in low:
        return (today() - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*(day|days|hour|hours)\s*ago", low)
    if m:
        n = int(m.group(1))
        if m.group(2).startswith("hour"):
            n = 0
        return (today() - timedelta(days=n)).isoformat()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    for fmt in ("%m/%d/%Y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def canon_url(u: str) -> str:
    p = urlsplit(u.strip())
    path = p.path.rstrip("/")
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, "", ""))


def sha(s: str, n=16) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:n]


def norm_title(t: str) -> str:
    t = t.lower()
    t = re.sub(r"\(.*?\)", " ", t)
    t = re.sub(r"[^a-z0-9& ]+", " ", t)
    t = re.sub(r"\b(new york|nyc|ny|jersey city|chicago|il|nj|usa|us|americas)\b", " ", t)
    return " ".join(t.split())


def norm_company(c: str) -> str:
    c = (c or "").lower()
    c = c.replace("&", " and ")
    c = re.sub(r"[^a-z0-9 ]+", " ", c)
    c = re.sub(r"\b(inc|llc|ltd|plc|co|corp|corporation|group|holdings|lp|the|na|n a|usa|us|americas|securities|capital markets|bank)\b", " ", c)
    return " ".join(c.split())
