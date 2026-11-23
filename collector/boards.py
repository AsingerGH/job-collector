"""Job-board search via JobSpy (LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google Jobs).
No login. LinkedIn rate-limits aggressively (and blocks some cloud IPs), so each
runner config decides which sites it hits and how hard."""
from __future__ import annotations

import time

from .util import parse_date


def search_boards(cfg: dict, runner: dict, log) -> tuple[list[dict], dict]:
    from jobspy import scrape_jobs  # imported lazily so tests don't need it

    sites = runner.get("sites", ["indeed"])
    hours_old = int(runner.get("hours_old", cfg.get("hours_old", 72)))
    per = int(runner.get("results_per_search", 40))
    health: dict[str, dict] = {s: {"ok": 0, "errors": 0, "rows": 0, "last_error": "", "skipped": 0} for s in sites}
    streak = {s: 0 for s in sites}   # consecutive blocks; after 3 we stop hitting that site this run
    rows: list[dict] = []

    for loc in cfg["locations"]:
        terms = cfg["terms"] if loc.get("all_terms", True) else cfg.get("trading_terms", cfg["terms"])
        for term in terms:
            for site in sites:
                if streak[site] >= 3:
                    health[site]["skipped"] += 1
                    continue
                try:
                    df = scrape_jobs(
                        site_name=[site],
                        search_term=term,
                        google_search_term=f"{term} jobs near {loc['name']} since {max(1, hours_old // 24)} days ago",
                        location=loc["name"],
                        distance=int(loc.get("distance", 15)),
                        results_wanted=per,
                        hours_old=hours_old,
                        country_indeed="USA",
                        fetch_description=bool(runner.get("linkedin_descriptions", True)) if site == "linkedin" else False,
                        description_format="markdown",
                        verbose=0,
                    )
                except Exception as e:  # one bad site/term must not kill the run
                    health[site]["errors"] += 1
                    health[site]["last_error"] = str(e)[:300]
                    streak[site] += 1
                    log(f"  ! {site} '{term}' @ {loc['name']}: {e}")
                    time.sleep(runner.get("sleep_after_error", 20))
                    continue
                errs = (getattr(df, "attrs", None) or {}).get("errors") or {}
                if errs:
                    health[site]["errors"] += 1
                    health[site]["last_error"] = str(errs.get(site, errs))[:300]
                    streak[site] += 1
                    log(f"  ! {site} '{term}' @ {loc['name']}: {health[site]['last_error']}")
                    if streak[site] >= 3:
                        log(f"  ! {site}: blocked 3 times in a row, skipping it for the rest of this run")
                    time.sleep(runner.get("sleep_after_error", 20))
                    continue
                streak[site] = 0
                health[site]["ok"] += 1
                n = 0
                for r in df.to_dict("records") if df is not None else []:
                    url = r.get("job_url_direct") or r.get("job_url") or ""
                    if not url or not r.get("title"):
                        continue
                    rows.append({
                        "company": str(r.get("company") or ""),
                        "title": str(r.get("title") or ""),
                        "location": _loc(r.get("location")),
                        "url": str(r.get("job_url") or url),
                        "url_direct": str(r.get("job_url_direct") or ""),
                        "date_posted": parse_date(r.get("date_posted")),
                        "description": str(r.get("description") or "")[:8000],
                        "job_type": _jt(r.get("job_type")),
                        "salary": _salary(r),
                        "source": site,
                        "search": term,
                    })
                    n += 1
                health[site]["rows"] += n
                time.sleep(float(runner.get("sleep_between", 4 if site == "linkedin" else 1.5)))
    return rows, health


def _loc(v) -> str:
    if isinstance(v, dict):
        return ", ".join(str(v[k]) for k in ("city", "state", "country") if v.get(k))
    return str(v or "")


def _jt(v) -> str:
    if isinstance(v, (list, tuple)):
        return ", ".join(getattr(x, "value", x) if not isinstance(x, str) else x for x in v)
    return str(v or "")


def _salary(r: dict) -> str:
    lo, hi = r.get("min_amount"), r.get("max_amount")
    try:
        if lo and lo == lo:
            return f"{int(lo):,}-{int(hi):,} {r.get('interval') or ''}".strip() if hi and hi == hi else f"{int(lo):,}+"
    except (TypeError, ValueError):
        pass
    return ""
