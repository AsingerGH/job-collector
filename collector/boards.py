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
        all_terms = runner.get("terms") or cfg["terms"]          # a runner may use a shorter list (laptop)
        terms = all_terms if loc.get("all_terms", True) else [t for t in cfg.get("trading_terms", all_terms) if t in all_terms] or all_terms[:6]
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
                if n == 0 and site == "linkedin":
                    # LinkedIn often answers a throttled request with an empty page instead of an error
                    streak[site] += 1
                    health[site]["empty"] = health[site].get("empty", 0) + 1
                    if streak[site] >= 3:
                        log(f"  ! {site}: 3 blocked/empty results in a row, skipping it for the rest of this run")
                elif n > 0:
                    streak[site] = 0
                time.sleep(float(runner.get("sleep_between", 4 if site == "linkedin" else 1.5)))

    # Company-targeted searches: for watchlist firms whose own job system we can't read,
    # search the boards by firm name so their roles don't depend on matching a title keyword.
    firms = runner.get("company_list") or []
    csites = [s for s in runner.get("company_sites", ["indeed"]) if s in sites]
    if firms and csites:
        from .util import norm_company
        cloc = cfg["locations"][0]["name"]
        for site in csites:
            health[site].setdefault("company_searches", 0)
            for firm, aliases in firms:
                if streak[site] >= 3:
                    break
                keys = {norm_company(a) for a in [firm, *aliases]}
                for word in runner.get("company_words", ["analyst", "trading"]):
                    try:
                        df = scrape_jobs(site_name=[site], search_term=f"{firm} {word}", location=cloc,
                                         distance=15, results_wanted=int(runner.get("company_results", 25)),
                                         hours_old=hours_old, country_indeed="USA",
                                         fetch_description=False, description_format="markdown", verbose=0)
                    except Exception as e:
                        health[site]["errors"] += 1
                        health[site]["last_error"] = str(e)[:300]
                        streak[site] += 1
                        time.sleep(runner.get("sleep_after_error", 20))
                        continue
                    health[site]["company_searches"] += 1
                    n = 0
                    for r in df.to_dict("records") if df is not None else []:
                        co = str(r.get("company") or "")
                        nc = norm_company(co)
                        if not nc or not any(k and (k == nc or k in nc or nc in k) for k in keys):
                            continue          # board returned some other firm's job
                        url = r.get("job_url_direct") or r.get("job_url") or ""
                        if not url or not r.get("title"):
                            continue
                        rows.append({
                            "company": co, "title": str(r.get("title") or ""),
                            "location": _loc(r.get("location")), "url": str(r.get("job_url") or url),
                            "url_direct": str(r.get("job_url_direct") or ""),
                            "date_posted": parse_date(r.get("date_posted")),
                            "description": str(r.get("description") or "")[:8000],
                            "job_type": _jt(r.get("job_type")), "salary": _salary(r),
                            "source": site, "search": f"company:{firm}",
                        })
                        n += 1
                    health[site]["rows"] += n
                    streak[site] = 0
                    time.sleep(float(runner.get("sleep_between", 1.5)))
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
