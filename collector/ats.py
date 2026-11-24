"""Fetchers for company-owned applicant tracking systems.

Each fetcher returns a list of raw job dicts with these keys:
  company, title, location, url, date_posted, description, req_id, ats
and raises on network failure (so the caller can record the source as unhealthy and
avoid wrongly marking that company's jobs as closed).

`needs_detail` lets the collector fetch full descriptions only for jobs that pass the
title/location prefilter (Workday, Eightfold and Oracle list endpoints omit them).
"""
from __future__ import annotations

import time
from typing import Callable

from .util import get_json, parse_date, post_json, strip_html

WORKDAY_TERMS = ["analyst", "trading", "markets", "sales", "intern"]


# ---------------------------------------------------------------- Greenhouse
def greenhouse(c: dict) -> list[dict]:
    host = "boards-api.eu.greenhouse.io" if c.get("region") == "eu" else "boards-api.greenhouse.io"
    data = get_json(f"https://{host}/v1/boards/{c['token']}/jobs", params={"content": "true"})
    out = []
    for j in data.get("jobs", []):
        out.append({
            "company": c["name"],
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""),
            "date_posted": parse_date(j.get("first_published") or j.get("updated_at")),
            "description": strip_html(j.get("content")),
            "req_id": str(j.get("requisition_id") or j.get("id")),
            "ats": "greenhouse",
        })
    return out


# --------------------------------------------------------------------- Lever
def lever(c: dict) -> list[dict]:
    host = "api.eu.lever.co" if c.get("region") == "eu" else "api.lever.co"
    data = get_json(f"https://{host}/v0/postings/{c['token']}", params={"mode": "json"})
    out = []
    for j in data:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or [cats.get("location", "")]
        desc = j.get("descriptionPlain", "") + "\n" + "\n".join(
            f"{l.get('text','')}: {strip_html(l.get('content',''))}" for l in j.get("lists", [])
        )
        out.append({
            "company": c["name"],
            "title": j.get("text", ""),
            "location": "; ".join(x for x in locs if x),
            "url": j.get("hostedUrl", ""),
            "date_posted": parse_date(j.get("createdAt")),
            "description": desc.strip(),
            "req_id": j.get("id", ""),
            "ats": "lever",
            "commitment": cats.get("commitment", ""),
        })
    return out


# --------------------------------------------------------------------- Ashby
def ashby(c: dict) -> list[dict]:
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{c['token']}",
                    params={"includeCompensation": "true"})
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations", [])]
        out.append({
            "company": c["name"],
            "title": j.get("title", ""),
            "location": "; ".join(x for x in locs if x),
            "url": j.get("jobUrl", ""),
            "date_posted": parse_date(j.get("publishedAt")),
            "description": j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
            "req_id": j.get("id", ""),
            "ats": "ashby",
        })
    return out


# ----------------------------------------------------------- SmartRecruiters
def smartrecruiters(c: dict) -> list[dict]:
    out, offset = [], 0
    while True:
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{c['token']}/postings",
                        params={"limit": 100, "offset": offset})
        for j in data.get("content", []):
            loc = j.get("location") or {}
            out.append({
                "company": c["name"],
                "title": j.get("name", ""),
                "location": ", ".join(x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x),
                "url": f"https://jobs.smartrecruiters.com/{c['token']}/{j.get('id')}",
                "date_posted": parse_date(j.get("releasedDate")),
                "description": "",
                "req_id": str(j.get("refNumber") or j.get("id")),
                "ats": "smartrecruiters",
                "_detail": f"https://api.smartrecruiters.com/v1/companies/{c['token']}/postings/{j.get('id')}",
            })
        offset += 100
        if offset >= data.get("totalFound", 0) or offset > 2000:
            break
    return out


def smartrecruiters_detail(job: dict) -> str:
    d = get_json(job["_detail"])
    secs = (d.get("jobAd") or {}).get("sections") or {}
    return "\n\n".join(strip_html((secs.get(k) or {}).get("text")) for k in
                       ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))


# ------------------------------------------------------------------- Workday
# Workday answers bursts from cloud IPs with HTTP 429. Calls paced ~2.5 s apart worked
# from GitHub Actions in the 2026-11-24 probe, so every Workday request in a run goes
# through one shared pacing lock.
import threading as _threading
_WD_LOCK = _threading.Lock()
_WD_LAST = [0.0]
WD_SPACING = 1.5


WD_DEADLINE = [0.0]   # set by the collector: no new Workday tenant starts after this time


def _wd_post(url, payload, headers):
    """POST with pacing; a 429 gets two long cool-downs before we give up on the tenant."""
    for attempt in range(2):
        _wd_pace()
        try:
            return post_json(url, payload, retries=0, headers=headers)
        except RuntimeError as e:
            if "429" not in str(e) or attempt == 1:
                raise
            time.sleep(20)


def _wd_pace():
    with _WD_LOCK:
        wait = _WD_LAST[0] + WD_SPACING - time.time()
        if wait > 0:
            time.sleep(wait)
        _WD_LAST[0] = time.time()


def workday(c: dict) -> list[dict]:
    """Uses Workday's public CXS JSON API, the same one the careers page itself calls."""
    tenant, dc, site = c["tenant"], c["dc"], c["site"]
    base = f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    seen: dict[str, dict] = {}
    if WD_DEADLINE[0] and time.time() > WD_DEADLINE[0]:
        raise RuntimeError("skipped: Workday time budget for this run used up")
    terms = c.get("terms") or WORKDAY_TERMS
    t0 = time.time()
    budget = float(c.get("budget_secs", 300))   # one slow tenant must not stall the whole run
    for term in terms:
        if time.time() - t0 > budget:
            break
        for page in range(int(c.get("max_pages", 3))):
            data = _wd_post(f"{base}/jobs", {"appliedFacets": {}, "limit": 20,
                                              "offset": page * 20, "searchText": term},
                            headers={"Origin": f"https://{tenant}.{dc}.myworkdayjobs.com",
                                      "Referer": f"https://{tenant}.{dc}.myworkdayjobs.com/en-US/{site}"})
            posts = data.get("jobPostings") or []
            for j in posts:
                path = j.get("externalPath")
                if not path or path in seen:
                    continue
                bullets = j.get("bulletFields") or []
                seen[path] = {
                    "company": c["name"],
                    "title": j.get("title", ""),
                    "location": j.get("locationsText", ""),
                    "url": f"https://{tenant}.{dc}.myworkdayjobs.com/en-US/{site}{path}",
                    "date_posted": parse_date(j.get("postedOn")),
                    "description": "",
                    "req_id": bullets[0] if bullets else path.rsplit("_", 1)[-1],
                    "ats": "workday",
                    "_detail": f"{base}{path}",
                }
            if len(posts) < 20:
                break
    return list(seen.values())


def workday_detail(job: dict) -> str:
    _wd_pace()
    d = get_json(job["_detail"], retries=4).get("jobPostingInfo") or {}
    extra = []
    if d.get("location"):
        job["location"] = "; ".join([d["location"]] + list(d.get("additionalLocations") or []))
    if d.get("startDate"):
        job["date_posted"] = parse_date(d["startDate"]) or job["date_posted"]
    if d.get("timeType"):
        extra.append(f"Time type: {d['timeType']}")
    return strip_html(d.get("jobDescription")) + ("\n" + "\n".join(extra) if extra else "")


# ------------------------------------------------- Eightfold (e.g. Morgan Stanley)
def eightfold(c: dict) -> list[dict]:
    host, domain = c["host"], c["domain"]
    seen = {}
    for term in c.get("terms") or ["analyst", "trading", "markets", "intern"]:
        for start in range(0, 100, 10):
            data = get_json(f"https://{host}/api/apply/v2/jobs",
                            params={"domain": domain, "query": term, "start": start, "num": 10,
                                    "sort_by": "timestamp"})
            pos = data.get("positions") or []
            for j in pos:
                jid = str(j.get("id"))
                if jid in seen:
                    continue
                seen[jid] = {
                    "company": c["name"],
                    "title": j.get("name", ""),
                    "location": "; ".join(j.get("locations") or [j.get("location", "")]),
                    "url": j.get("canonicalPositionUrl") or f"https://{host}/careers?pid={jid}&domain={domain}",
                    "date_posted": parse_date(j.get("t_create")),
                    "description": strip_html(j.get("job_description", "")),
                    "req_id": j.get("display_job_id") or jid,
                    "ats": "eightfold",
                }
            if len(pos) < 10:
                break
    return list(seen.values())


# ---------------------------------------------- Oracle Cloud HCM (e.g. J.P. Morgan)
def oracle(c: dict) -> list[dict]:
    sites = c["site"] if isinstance(c["site"], list) else [c["site"]]
    out = []
    for site in sites:
        out += _oracle_site(c, site)
    return out


def _oracle_site(c: dict, site: str) -> list[dict]:
    host = c["host"]
    seen = {}
    for term in c.get("terms") or ["analyst", "trading", "markets", "intern"]:
        for offset in range(0, 150, 25):
            finder = (f'findReqs;siteNumber={site},facetsList=NONE,limit=25,offset={offset},'
                      f'keyword="{term}",sortBy=POSTING_DATES_DESC')
            data = get_json(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                            params={"onlyData": "true", "expand": "requisitionList.secondaryLocations",
                                    "finder": finder})
            items = (data.get("items") or [{}])[0].get("requisitionList") or []
            for j in items:
                jid = str(j.get("Id"))
                if jid in seen:
                    continue
                locs = [j.get("PrimaryLocation", "")] + [s.get("Name", "") for s in j.get("secondaryLocations") or []]
                seen[jid] = {
                    "company": c["name"],
                    "title": j.get("Title", ""),
                    "location": "; ".join(x for x in locs if x),
                    "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}",
                    "date_posted": parse_date(j.get("PostedDate")),
                    "description": strip_html(j.get("ShortDescriptionStr", "")),
                    "req_id": jid,
                    "ats": "oracle",
                    "_detail": (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
                                f"?expand=all&onlyData=true&finder=ById;Id=\"{jid}\",siteNumber={site}"),
                }
            if len(items) < 25:
                break
    return list(seen.values())


def oracle_detail(job: dict) -> str:
    d = (get_json(job["_detail"]).get("items") or [{}])[0]
    return "\n\n".join(strip_html(d.get(k)) for k in
                       ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr") if d.get(k))


from .generic import icims as _icims, sitemap as _sitemap  # noqa: E402

FETCHERS: dict[str, Callable[[dict], list[dict]]] = {
    "sitemap": _sitemap,
    "icims": _icims,
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
    "eightfold": eightfold,
    "oracle": oracle,
}

DETAIL: dict[str, Callable[[dict], str]] = {
    "workday": workday_detail,
    "smartrecruiters": smartrecruiters_detail,
    "oracle": oracle_detail,
}
