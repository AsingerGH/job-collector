"""Fingerprint the job software behind each no-feed firm's careers site (runs in GitHub Actions)."""
from __future__ import annotations
import json, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import requests
sys.path.insert(0, ".")
from tools.probe_targets import T

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
S = requests.Session(); S.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
WD_LOCK = threading.Lock()

PATTERNS = {
 "workday": r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)",
 "eightfold": r"([a-z0-9-]+)\.eightfold\.ai",
 "oracle": r"([a-z0-9-]+\.fa(?:\.[a-z0-9]+)?\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z]+/sites/([A-Za-z0-9_]+)",
 "greenhouse": r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9]+)",
 "lever": r"jobs\.lever\.co/([a-z0-9-]+)",
 "ashby": r"jobs\.ashbyhq\.com/([A-Za-z0-9.-]+)",
 "smartrecruiters": r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9]+)",
 "icims": r"([a-z0-9-]+\.icims\.com)",
 "taleo": r"([a-z0-9-]+\.taleo\.net)",
 "successfactors": r"(career\d*\.(?:sapsf|successfactors)\.(?:com|eu)[^\"' ]*company=([A-Za-z0-9_]+))",
 "avature": r"([a-z0-9-]+\.avature\.net)",
 "talnet": r"([a-z0-9-]+\.tal\.net)",
 "phenom": r"(cdn\.phenompeople\.com|phenompeople)",
 "radancy": r"(tbcdn\.talentbrew\.com|radancy|/search-jobs/results)",
 "jobvite": r"jobs\.jobvite\.com/([a-z0-9-]+)",
 "workable": r"apply\.workable\.com/([a-z0-9-]+)",
 "ukg": r"([a-z0-9]+\.ultipro\.com|recruiting\d*\.ultipro\.com)",
 "adp": r"(workforcenow\.adp\.com[^\"' ]*cid=[a-z0-9-]+)",
 "dayforce": r"(jobs\.dayforcehcm\.com/[^\"' ]+)",
 "paylocity": r"(recruiting\.paylocity\.com[^\"' ]+)",
 "bamboohr": r"([a-z0-9-]+\.bamboohr\.com)",
 "rippling": r"ats\.rippling\.com/([a-z0-9-]+)",
 "pinpoint": r"([a-z0-9-]+\.pinpointhq\.com)",
 "teamtailor": r"([a-z0-9-]+\.teamtailor\.com)",
 "breezy": r"([a-z0-9-]+\.breezy\.hr)",
 "gs_higher": r"(higher\.gs\.com)",
}

def get(u, **kw):
    try:
        r = S.get(u, timeout=20, allow_redirects=True, **kw)
        return r
    except Exception as e:
        return e

def fingerprint(text):
    found = {}
    for k, p in PATTERNS.items():
        m = re.findall(p, text)
        if m:
            found[k] = sorted({(x if isinstance(x, str) else "|".join(x)) for x in m})[:6]
    return found

def jsonld_jobs(text):
    return len(re.findall(r'"@type"\s*:\s*"JobPosting"', text))

def sitemap(host):
    out = {}
    for path in ["/robots.txt", "/sitemap.xml", "/sitemap_index.xml"]:
        r = get(f"https://{host}{path}")
        if isinstance(r, Exception) or r.status_code != 200:
            out[path] = None if isinstance(r, Exception) else r.status_code
            continue
        t = r.text
        if path == "/robots.txt":
            out[path] = re.findall(r"(?im)^sitemap:\s*(\S+)", t)[:5]
        else:
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", t)
            out[path] = {"n": len(locs), "jobish": sum(1 for l in locs if re.search(r"/job", l, re.I)),
                         "sample": locs[:3], "subs": [l for l in locs if "sitemap" in l.lower()][:5]}
    return out

def wd_test(tenant, dc, site):
    with WD_LOCK:
        time.sleep(3)
        try:
            r = S.post(f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                       json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "analyst"},
                       headers={"Origin": f"https://{tenant}.{dc}.myworkdayjobs.com"}, timeout=20)
            j = r.json() if r.status_code == 200 else {}
            return {"status": r.status_code, "total": j.get("total"), "sample": [x.get("title") for x in j.get("jobPostings", [])[:3]]}
        except Exception as e:
            return {"error": str(e)[:120]}

def probe(name):
    res = {"name": name, "urls": []}
    hosts = set()
    for u in T[name]:
        r = get(u)
        if isinstance(r, Exception):
            res["urls"].append({"url": u, "error": str(r)[:150]}); continue
        t = r.text if "text" in r.headers.get("content-type", "") or "xml" in r.headers.get("content-type", "") else ""
        e = {"url": u, "status": r.status_code, "final": r.url, "len": len(t),
             "fp": fingerprint(t + " " + r.url), "jsonld": jsonld_jobs(t),
             "title": (re.search(r"<title>([^<]{0,120})", t) or [None, ""])[1].strip()}
        if "sitemap" in u:
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", t)
            e["sitemap"] = {"n": len(locs), "jobish": sum(1 for l in locs if "/job" in l.lower()), "sample": locs[:3]}
        res["urls"].append(e)
        if r.status_code == 200:
            hosts.add(urlparse(r.url).netloc)
        wd = e["fp"].get("workday", [])
        for w in wd[:2]:
            tenant, dc, site = w.split("|")
            if site.lower() in ("wday", "en-us"):
                continue
            e.setdefault("wd_test", {})[w] = wd_test(tenant, dc, site)
    res["sitemaps"] = {h: sitemap(h) for h in list(hosts)[:2] if "myworkdayjobs" not in h}
    return res

if __name__ == "__main__":
    names = sys.argv[1:] or list(T)
    with ThreadPoolExecutor(8) as ex:
        out = list(ex.map(probe, names))
    json.dump(out, open("data/probe.json", "w"), indent=1)
    print("probed", len(out))
