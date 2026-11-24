"""Vendor-agnostic readers for career sites that have no JSON job API we know of.

sitemap(c): reads the site's XML sitemap (most career platforms - Radancy/TalentBrew,
Phenom, iCIMS, SuccessFactors, custom sites - publish one listing every open job page),
keeps job URLs whose slug looks relevant, then reads each candidate page's schema.org
JobPosting data (the structured block Google for Jobs relies on) for title, location,
dates and description. A job that disappears from the sitemap is closed.
"""
from __future__ import annotations

import gzip
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from .util import parse_date, session, strip_html

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>(?:\s*<lastmod>\s*([^<\s]+)\s*</lastmod>)?", re.I)
_SLUG_RELEVANT = re.compile(
    r"(trad|sales|market|desk|execution|equit|fixed-income|rates|credit|derivativ|option|commodit|"
    r"-fx-|foreign-exchange|futures|structur|research|analyst|associate|graduate|campus|program|"
    r"capital|invest|bank|securiti|prime|financ|delta-one|etf|municipal|syndicate|portfolio|"
    r"liquidity|ficc|intern|summer|treasury)", re.I)
_SLUG_JUNK = re.compile(
    r"(engineer|developer|software|technolog|cyber|data-scien|machine-learning|devops|nurse|"
    r"teller|branch|mortgage|loan-officer|customer-service|call-center|payroll|recruit|"
    r"facilities|administrative|executive-assistant|compliance|audit|legal|counsel|"
    r"vice-president|director|managing-director|head-of|chief|principal|senior|-svp|-avp|-vp-)", re.I)
_BAD_TITLE = re.compile(r"(sign on|sign in|log ?in|page not found|error|access denied|just a moment)", re.I)
_CITY = re.compile(r"(new-york|nyc|jersey-city|hoboken|weehawken|chicago)", re.I)
_ANY_CITY = re.compile(r"/job/([a-z-]+)/", re.I)  # Radancy-style /job/<city>/<slug>/<org>/<id>


def _get(url: str, timeout=25) -> str:
    r = session().get(url, timeout=timeout)
    r.raise_for_status()
    data = r.content
    if url.endswith(".gz") or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode("utf-8", "replace")


def sitemap_urls(roots, include: str | None = None, max_children: int = 25) -> list[tuple[str, str]]:
    """Return (url, lastmod) for every page in the sitemap(s), following sitemap indexes."""
    inc = re.compile(include or r"/jobs?/|/job-|/position|/vacanc|/opening|jobid|job_id|/roles?/", re.I)
    out, queue, seen = {}, list(roots if isinstance(roots, list) else [roots]), set()
    while queue and len(seen) < max_children:
        u = queue.pop(0)
        if u in seen:
            continue
        seen.add(u)
        text = _get(u)
        if "<sitemapindex" in text[:2000].lower():
            kids = [m[0] for m in _LOC_RE.findall(text)]
            jobby = [k for k in kids if re.search(r"job|career|position|vacanc|requisition", k, re.I)]
            queue += jobby or kids
            continue
        for loc, mod in _LOC_RE.findall(text):
            if inc.search(loc):
                out[loc] = mod or ""
    return sorted(out.items(), key=lambda x: x[1], reverse=True)


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def jobposting(html: str) -> dict | None:
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip(), strict=False)
        except Exception:
            continue
        for o in _walk(data):
            t = o.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                return o
    return None


def _location(jp: dict) -> str:
    locs = jp.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    out = []
    for l in locs:
        a = (l or {}).get("address") or {}
        if isinstance(a, str):
            out.append(a)
            continue
        city = a.get("addressLocality") or ""
        reg = a.get("addressRegion") or ""
        if isinstance(city, dict):
            city = city.get("name", "")
        out.append(", ".join(x for x in (city, reg) if x))
    if jp.get("jobLocationType") == "TELECOMMUTE":
        out.append("Remote")
    return "; ".join(x for x in out if x)


def _fallback(company: str, url: str, html: str, ats: str) -> dict | None:
    """Page without schema.org data: take the title from og:title/<h1> and the city from the URL."""
    m = (re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.I)
         or re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I))
    if not m:
        return None
    title = strip_html(m.group(1)).split(" | ")[0].strip()
    city = _CITY.search(url)
    body = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html)
    return {"company": company, "title": title,
            "location": city.group(1).replace("-", " ").title() if city else "",
            "url": url, "date_posted": None, "deadline": None,
            "description": strip_html(body)[:6000],
            "req_id": url.rstrip("/").rsplit("/", 1)[-1], "ats": ats}


def page_job(company: str, url: str, ats: str = "sitemap") -> dict | None:
    html = _get(url)
    jp = jobposting(html)
    if not jp:
        return _fallback(company, url, html, ats)
    org = jp.get("hiringOrganization") or {}
    return {
        "company": company,
        "title": strip_html(jp.get("title") or ""),
        "location": _location(jp),
        "url": url,
        "date_posted": parse_date(jp.get("datePosted")),
        "deadline": parse_date(jp.get("validThrough")),
        "description": strip_html(jp.get("description") or ""),
        "req_id": str((jp.get("identifier") or {}).get("value", "") if isinstance(jp.get("identifier"), dict)
                      else jp.get("identifier") or url.rstrip("/").rsplit("/", 1)[-1]),
        "ats": ats,
        "employment_type": jp.get("employmentType") or "",
        "_org": org.get("name", "") if isinstance(org, dict) else "",
    }


def slug_candidate(url: str) -> bool:
    path = url.split("//", 1)[-1].split("/", 1)[-1].lower()
    if _SLUG_JUNK.search(path):
        return False
    m = _ANY_CITY.search("/" + path)
    if m and not _CITY.search(m.group(1)) and re.search(r"[a-z]", m.group(1)):
        # slug names a city and it isn't one of ours (Radancy-style URLs)
        if not re.search(r"multiple|various|united-states|americas", m.group(1)):
            return False
    return bool(_SLUG_RELEVANT.search(path))


def sitemap(c: dict) -> list[dict]:
    urls = sitemap_urls(c["sitemap"], c.get("include"))
    if not urls:
        raise RuntimeError("sitemap returned no job URLs")
    req = re.compile(c["require"], re.I) if c.get("require") else None
    use_slug = c.get("slug_filter", True)
    cands = [u for u, _ in urls if (not use_slug or slug_candidate(u)) and (not req or req.search(u))][: int(c.get("max_detail", 60))]
    out: list[dict] = []

    def one(u):
        time.sleep(0.3)
        try:
            return page_job(c["name"], u, c.get("ats_label", "sitemap"))
        except Exception:
            return None

    with ThreadPoolExecutor(6) as ex:
        for j in ex.map(one, cands):
            if j and j["title"] and not _BAD_TITLE.search(j["title"]):
                out.append(j)
    if cands and not out:
        raise RuntimeError(f"{len(cands)} candidate pages but no readable job data")

    class _Jobs(list):
        pass
    res = _Jobs(out)
    res.live_urls = [u for u, _ in urls]   # every job page in the sitemap is a live posting
    return res


# ------------------------------------------------------------------- iCIMS
_ICIMS_LINK = re.compile(r'href="(https://[a-z0-9-]+\.icims\.com/jobs/(\d+)/([a-z0-9-]+)/job[^"]*)"[^>]*>(.*?)</a>', re.I | re.S)


def icims(c: dict) -> list[dict]:
    """iCIMS career portals list jobs on paged HTML search pages (no login); each job page
    then carries schema.org JobPosting data."""
    host = c["host"]
    found: dict[str, str] = {}
    for page in range(int(c.get("max_pages", 15))):
        html = _get(f"https://{host}/jobs/search?ss=1&in_iframe=1&pr={page}")
        links = _ICIMS_LINK.findall(html)
        new = 0
        for url, jid, slug, _ in links:
            if jid not in found:
                found[jid] = url.split("?")[0]
                new += 1
        if not links or not new:
            break
        time.sleep(0.5)
    if not found:
        raise RuntimeError("iCIMS search pages listed no jobs")
    urls = list(found.values())
    cands = [u for u in urls if slug_candidate(u)][: int(c.get("max_detail", 60))]
    out = []

    def one(u):
        try:
            return page_job(c["name"], u + "?in_iframe=1", "icims")
        except Exception:
            return None

    with ThreadPoolExecutor(6) as ex:
        for j in ex.map(one, cands):
            if j and j["title"]:
                j["url"] = j["url"].split("?")[0]
                out.append(j)

    class _Jobs(list):
        pass
    res = _Jobs(out)
    res.live_urls = urls
    return res
